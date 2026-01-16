"""
DiskForge Safety Manager.

Implements safety features including danger mode, confirmation requirements,
and preflight checks for destructive operations.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum, auto
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from diskforge.core.logging import get_logger

if TYPE_CHECKING:
    from diskforge.core.config import SafetyConfig

logger = get_logger(__name__)


class DangerMode(Enum):
    """Danger mode states."""

    DISABLED = auto()  # Read-only, no destructive operations
    ENABLED = auto()  # Destructive operations allowed with confirmation
    ACKNOWLEDGED = auto()  # User has acknowledged risks for current session


class OperationType(Enum):
    """Types of operations with their risk levels."""

    READ_ONLY = auto()  # Safe: inventory, SMART, etc.
    CREATE = auto()  # Moderate: create partition, image
    MODIFY = auto()  # Dangerous: format, resize
    DELETE = auto()  # Very dangerous: delete partition
    CLONE = auto()  # Destructive: overwrites target
    RESTORE = auto()  # Destructive: overwrites target disk/partition


@dataclass
class PreflightCheck:
    """Result of a single preflight check."""

    name: str
    passed: bool
    message: str
    severity: str = "info"  # info, warning, error, critical
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class PreflightReport:
    """Complete preflight check report."""

    checks: list[PreflightCheck] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def has_errors(self) -> bool:
        return any(c.severity in ("error", "critical") and not c.passed for c in self.checks)

    @property
    def has_warnings(self) -> bool:
        return any(c.severity == "warning" and not c.passed for c in self.checks)

    def get_summary(self) -> str:
        """Get human-readable summary."""
        lines = [f"Preflight Check Report ({self.timestamp.isoformat()})"]
        lines.append("=" * 60)

        passed = sum(1 for c in self.checks if c.passed)
        total = len(self.checks)
        lines.append(f"Results: {passed}/{total} checks passed")
        lines.append("")

        for check in self.checks:
            status = "✓" if check.passed else "✗"
            lines.append(f"[{status}] {check.name}: {check.message}")
            if check.details:
                for key, value in check.details.items():
                    lines.append(f"    {key}: {value}")

        return "\n".join(lines)


@dataclass
class ExecutionPlan:
    """Human-readable execution plan for an operation."""

    operation_type: OperationType
    description: str
    target: str
    steps: list[str]
    warnings: list[str] = field(default_factory=list)
    estimated_duration: str | None = None
    preflight_report: PreflightReport | None = None
    confirmation_string: str | None = None

    def get_plan_text(self) -> str:
        """Get human-readable plan text."""
        lines = ["=" * 60]
        lines.append(f"OPERATION: {self.description}")
        lines.append(f"TARGET: {self.target}")
        lines.append(f"TYPE: {self.operation_type.name}")
        lines.append("=" * 60)

        if self.warnings:
            lines.append("")
            lines.append("⚠️  WARNINGS:")
            for warning in self.warnings:
                lines.append(f"   • {warning}")

        lines.append("")
        lines.append("EXECUTION STEPS:")
        for i, step in enumerate(self.steps, 1):
            lines.append(f"   {i}. {step}")

        if self.estimated_duration:
            lines.append("")
            lines.append(f"Estimated duration: {self.estimated_duration}")

        if self.preflight_report:
            lines.append("")
            lines.append(self.preflight_report.get_summary())

        if self.confirmation_string:
            lines.append("")
            lines.append("=" * 60)
            lines.append("To proceed, type the following confirmation string:")
            lines.append(f"  {self.confirmation_string}")
            lines.append("=" * 60)

        return "\n".join(lines)


class SafetyManager:
    """Manages safety features for DiskForge operations."""

    def __init__(self, config: SafetyConfig) -> None:
        self.config = config
        self._danger_mode = DangerMode.DISABLED
        self._danger_mode_enabled_at: datetime | None = None
        self._acknowledged_operations: set[str] = set()
        self._lock = threading.Lock()

    @property
    def danger_mode(self) -> DangerMode:
        """Get current danger mode state."""
        with self._lock:
            # Auto-disable danger mode after timeout
            if self._danger_mode == DangerMode.ENABLED:
                if self._danger_mode_enabled_at:
                    elapsed = datetime.now() - self._danger_mode_enabled_at
                    if elapsed > timedelta(seconds=self.config.confirmation_timeout_seconds):
                        logger.info("Danger mode auto-disabled due to timeout")
                        self._danger_mode = DangerMode.DISABLED
                        self._danger_mode_enabled_at = None
            return self._danger_mode

    def enable_danger_mode(self, acknowledgment: str) -> bool:
        """
        Enable danger mode with user acknowledgment.
        Requires typing 'I understand the risks' or similar.
        """
        expected = "I understand the risks"
        if acknowledgment.strip().lower() != expected.lower():
            logger.warning(
                "Failed to enable danger mode: incorrect acknowledgment",
                expected=expected,
                received=acknowledgment,
            )
            return False

        with self._lock:
            self._danger_mode = DangerMode.ENABLED
            self._danger_mode_enabled_at = datetime.now()
            self._acknowledged_operations.clear()

        logger.warning(
            "Danger mode enabled",
            timeout_seconds=self.config.confirmation_timeout_seconds,
        )
        return True

    def disable_danger_mode(self) -> None:
        """Disable danger mode and return to read-only."""
        with self._lock:
            self._danger_mode = DangerMode.DISABLED
            self._danger_mode_enabled_at = None
            self._acknowledged_operations.clear()

        logger.info("Danger mode disabled")

    def is_operation_allowed(self, operation_type: OperationType) -> tuple[bool, str]:
        """
        Check if an operation type is allowed in current mode.
        Returns (allowed, reason).
        """
        # Read-only operations are always allowed
        if operation_type == OperationType.READ_ONLY:
            return True, "Read-only operations are always allowed"

        # Check danger mode
        current_mode = self.danger_mode
        if current_mode == DangerMode.DISABLED:
            return False, (
                f"Operation '{operation_type.name}' requires Danger Mode. "
                "Enable Danger Mode to perform destructive operations."
            )

        return True, "Operation allowed in Danger Mode"

    def generate_confirmation_string(self, target_identifier: str) -> str:
        """Generate a confirmation string that includes the target identifier."""
        # Sanitize target identifier
        safe_target = re.sub(r"[^a-zA-Z0-9/_-]", "", target_identifier)
        return f"DESTROY-{safe_target.upper()}"

    def verify_confirmation(
        self,
        target_identifier: str,
        user_input: str,
        operation_id: str,
    ) -> tuple[bool, str]:
        """
        Verify user confirmation for destructive operation.
        Returns (verified, message).
        """
        expected = self.generate_confirmation_string(target_identifier)

        if user_input.strip() != expected:
            logger.warning(
                "Confirmation verification failed",
                expected=expected,
                received=user_input,
                operation_id=operation_id,
            )
            return False, f"Confirmation mismatch. Expected: {expected}"

        with self._lock:
            self._acknowledged_operations.add(operation_id)

        logger.info(
            "Operation confirmed",
            operation_id=operation_id,
            target=target_identifier,
        )
        return True, "Confirmation verified"

    def is_operation_confirmed(self, operation_id: str) -> bool:
        """Check if an operation has been confirmed."""
        with self._lock:
            return operation_id in self._acknowledged_operations

    def create_execution_plan(
        self,
        operation_type: OperationType,
        description: str,
        target: str,
        steps: list[str],
        warnings: list[str] | None = None,
        estimated_duration: str | None = None,
        preflight_report: PreflightReport | None = None,
    ) -> ExecutionPlan:
        """Create an execution plan for user review."""
        confirmation_string = None
        if operation_type not in (OperationType.READ_ONLY, OperationType.CREATE):
            confirmation_string = self.generate_confirmation_string(target)

        return ExecutionPlan(
            operation_type=operation_type,
            description=description,
            target=target,
            steps=steps,
            warnings=warnings or [],
            estimated_duration=estimated_duration,
            preflight_report=preflight_report,
            confirmation_string=confirmation_string,
        )


class PreflightChecker:
    """Performs preflight checks before operations."""

    def __init__(self) -> None:
        self._checks: list[tuple[str, Any]] = []

    def add_check(self, name: str, check_func: Any) -> None:
        """Add a preflight check function."""
        self._checks.append((name, check_func))

    def run_checks(self, context: dict[str, Any]) -> PreflightReport:
        """Run all preflight checks and return report."""
        report = PreflightReport()

        for name, check_func in self._checks:
            try:
                result = check_func(context)
                if isinstance(result, PreflightCheck):
                    report.checks.append(result)
                elif isinstance(result, bool):
                    report.checks.append(
                        PreflightCheck(
                            name=name,
                            passed=result,
                            message="Passed" if result else "Failed",
                        )
                    )
            except Exception as e:
                report.checks.append(
                    PreflightCheck(
                        name=name,
                        passed=False,
                        message=f"Check failed with error: {e}",
                        severity="error",
                    )
                )

        return report


def check_power_status(context: dict[str, Any]) -> PreflightCheck:
    """Check if system is on AC power (not battery)."""
    try:
        import psutil

        battery = psutil.sensors_battery()
        if battery is None:
            return PreflightCheck(
                name="Power Status",
                passed=True,
                message="No battery detected (desktop/server)",
            )

        if battery.power_plugged:
            return PreflightCheck(
                name="Power Status",
                passed=True,
                message="System is on AC power",
                details={"battery_percent": battery.percent},
            )
        else:
            return PreflightCheck(
                name="Power Status",
                passed=battery.percent > 50,
                message=f"System on battery ({battery.percent}%)",
                severity="warning" if battery.percent > 50 else "error",
                details={"battery_percent": battery.percent},
            )
    except Exception as e:
        return PreflightCheck(
            name="Power Status",
            passed=True,
            message=f"Could not check power status: {e}",
            severity="info",
        )


def check_target_size(context: dict[str, Any]) -> PreflightCheck:
    """Check if target has sufficient size."""
    source_size = context.get("source_size", 0)
    target_size = context.get("target_size", 0)

    if target_size == 0:
        return PreflightCheck(
            name="Target Size",
            passed=False,
            message="Could not determine target size",
            severity="error",
        )

    if target_size < source_size:
        return PreflightCheck(
            name="Target Size",
            passed=False,
            message=f"Target ({target_size} bytes) is smaller than source ({source_size} bytes)",
            severity="error",
            details={"source_size": source_size, "target_size": target_size},
        )

    return PreflightCheck(
        name="Target Size",
        passed=True,
        message="Target has sufficient size",
        details={"source_size": source_size, "target_size": target_size},
    )


def check_not_mounted(context: dict[str, Any]) -> PreflightCheck:
    """Check if target is not mounted."""
    target_path = context.get("target_path", "")
    mounted_paths = context.get("mounted_paths", [])

    if target_path in mounted_paths:
        return PreflightCheck(
            name="Mount Status",
            passed=False,
            message=f"Target {target_path} is currently mounted",
            severity="error",
            details={"mounted_paths": mounted_paths},
        )

    return PreflightCheck(
        name="Mount Status",
        passed=True,
        message="Target is not mounted",
    )


def create_standard_preflight_checker() -> PreflightChecker:
    """Create a preflight checker with standard checks."""
    checker = PreflightChecker()
    checker.add_check("Power Status", check_power_status)
    checker.add_check("Target Size", check_target_size)
    checker.add_check("Mount Status", check_not_mounted)
    return checker
