"""
Tests for diskforge.core.safety module.
"""

import pytest

from diskforge.core.config import SafetyConfig
from diskforge.core.safety import (
    DangerMode,
    ExecutionPlan,
    OperationType,
    PreflightCheck,
    PreflightChecker,
    PreflightReport,
    SafetyManager,
    check_power_status,
    check_target_size,
    check_not_mounted,
)


class TestDangerMode:
    """Tests for DangerMode enum."""

    def test_danger_mode_values(self) -> None:
        assert DangerMode.DISABLED.name == "DISABLED"
        assert DangerMode.ENABLED.name == "ENABLED"
        assert DangerMode.ACKNOWLEDGED.name == "ACKNOWLEDGED"


class TestPreflightCheck:
    """Tests for PreflightCheck."""

    def test_passed_check(self) -> None:
        check = PreflightCheck(name="Test Check", passed=True, message="OK")
        assert check.passed is True
        assert check.severity == "info"

    def test_failed_check(self) -> None:
        check = PreflightCheck(
            name="Test Check",
            passed=False,
            message="Failed",
            severity="error",
        )
        assert check.passed is False
        assert check.severity == "error"


class TestPreflightReport:
    """Tests for PreflightReport."""

    def test_all_passed(self) -> None:
        report = PreflightReport(
            checks=[
                PreflightCheck(name="Check 1", passed=True, message="OK"),
                PreflightCheck(name="Check 2", passed=True, message="OK"),
            ]
        )
        assert report.all_passed is True
        assert report.has_errors is False
        assert report.has_warnings is False

    def test_has_errors(self) -> None:
        report = PreflightReport(
            checks=[
                PreflightCheck(name="Check 1", passed=True, message="OK"),
                PreflightCheck(
                    name="Check 2", passed=False, message="Error", severity="error"
                ),
            ]
        )
        assert report.all_passed is False
        assert report.has_errors is True

    def test_has_warnings(self) -> None:
        report = PreflightReport(
            checks=[
                PreflightCheck(name="Check 1", passed=True, message="OK"),
                PreflightCheck(
                    name="Check 2", passed=False, message="Warning", severity="warning"
                ),
            ]
        )
        assert report.has_warnings is True

    def test_get_summary(self) -> None:
        report = PreflightReport(
            checks=[
                PreflightCheck(name="Check 1", passed=True, message="OK"),
                PreflightCheck(name="Check 2", passed=False, message="Failed"),
            ]
        )
        summary = report.get_summary()
        assert "1/2 checks passed" in summary
        assert "Check 1" in summary
        assert "Check 2" in summary


class TestSafetyManager:
    """Tests for SafetyManager."""

    def test_initial_danger_mode(self) -> None:
        config = SafetyConfig()
        manager = SafetyManager(config)
        assert manager.danger_mode == DangerMode.DISABLED

    def test_enable_danger_mode_correct(self) -> None:
        config = SafetyConfig()
        manager = SafetyManager(config)

        result = manager.enable_danger_mode("I understand the risks")

        assert result is True
        assert manager.danger_mode == DangerMode.ENABLED

    def test_enable_danger_mode_incorrect(self) -> None:
        config = SafetyConfig()
        manager = SafetyManager(config)

        result = manager.enable_danger_mode("wrong acknowledgment")

        assert result is False
        assert manager.danger_mode == DangerMode.DISABLED

    def test_enable_danger_mode_case_insensitive(self) -> None:
        config = SafetyConfig()
        manager = SafetyManager(config)

        result = manager.enable_danger_mode("i UNDERSTAND the RISKS")

        assert result is True
        assert manager.danger_mode == DangerMode.ENABLED

    def test_disable_danger_mode(self) -> None:
        config = SafetyConfig()
        manager = SafetyManager(config)
        manager.enable_danger_mode("I understand the risks")

        manager.disable_danger_mode()

        assert manager.danger_mode == DangerMode.DISABLED

    def test_is_operation_allowed_read_only(self) -> None:
        config = SafetyConfig()
        manager = SafetyManager(config)

        allowed, reason = manager.is_operation_allowed(OperationType.READ_ONLY)

        assert allowed is True

    def test_is_operation_allowed_destructive_without_danger_mode(self) -> None:
        config = SafetyConfig()
        manager = SafetyManager(config)

        allowed, reason = manager.is_operation_allowed(OperationType.DELETE)

        assert allowed is False
        assert "Danger Mode" in reason

    def test_is_operation_allowed_destructive_with_danger_mode(self) -> None:
        config = SafetyConfig()
        manager = SafetyManager(config)
        manager.enable_danger_mode("I understand the risks")

        allowed, reason = manager.is_operation_allowed(OperationType.DELETE)

        assert allowed is True

    def test_generate_confirmation_string(self) -> None:
        config = SafetyConfig()
        manager = SafetyManager(config)

        confirm = manager.generate_confirmation_string("/dev/sda")

        assert "DESTROY" in confirm
        assert "SDA" in confirm

    def test_verify_confirmation_correct(self) -> None:
        config = SafetyConfig()
        manager = SafetyManager(config)

        confirm_string = manager.generate_confirmation_string("/dev/sda")
        verified, msg = manager.verify_confirmation("/dev/sda", confirm_string, "op1")

        assert verified is True

    def test_verify_confirmation_incorrect(self) -> None:
        config = SafetyConfig()
        manager = SafetyManager(config)

        verified, msg = manager.verify_confirmation("/dev/sda", "wrong", "op1")

        assert verified is False

    def test_create_execution_plan(self) -> None:
        config = SafetyConfig()
        manager = SafetyManager(config)

        plan = manager.create_execution_plan(
            operation_type=OperationType.DELETE,
            description="Delete partition",
            target="/dev/sda1",
            steps=["Step 1", "Step 2"],
            warnings=["Warning 1"],
        )

        assert plan.operation_type == OperationType.DELETE
        assert plan.target == "/dev/sda1"
        assert len(plan.steps) == 2
        assert len(plan.warnings) == 1
        assert plan.confirmation_string is not None


class TestExecutionPlan:
    """Tests for ExecutionPlan."""

    def test_get_plan_text(self) -> None:
        plan = ExecutionPlan(
            operation_type=OperationType.CLONE,
            description="Clone disk",
            target="/dev/sdb",
            steps=["Copy data", "Verify"],
            warnings=["Data will be lost"],
        )

        text = plan.get_plan_text()

        assert "Clone disk" in text
        assert "/dev/sdb" in text
        assert "Copy data" in text
        assert "Data will be lost" in text


class TestPreflightChecker:
    """Tests for PreflightChecker."""

    def test_add_and_run_checks(self) -> None:
        checker = PreflightChecker()

        checker.add_check("Always Pass", lambda ctx: True)
        checker.add_check("Always Fail", lambda ctx: False)

        report = checker.run_checks({})

        assert len(report.checks) == 2
        assert report.checks[0].passed is True
        assert report.checks[1].passed is False

    def test_check_returns_preflight_check(self) -> None:
        checker = PreflightChecker()

        checker.add_check(
            "Custom Check",
            lambda ctx: PreflightCheck(
                name="Custom",
                passed=True,
                message="Custom OK",
            ),
        )

        report = checker.run_checks({})

        assert report.checks[0].message == "Custom OK"

    def test_check_exception_handling(self) -> None:
        checker = PreflightChecker()

        def failing_check(ctx: dict) -> bool:
            raise ValueError("Check error")

        checker.add_check("Failing Check", failing_check)

        report = checker.run_checks({})

        assert report.checks[0].passed is False
        assert "error" in report.checks[0].message.lower()


class TestPreflightFunctions:
    """Tests for preflight check functions."""

    def test_check_target_size_sufficient(self) -> None:
        context = {"source_size": 1000, "target_size": 2000}
        result = check_target_size(context)
        assert result.passed is True

    def test_check_target_size_insufficient(self) -> None:
        context = {"source_size": 2000, "target_size": 1000}
        result = check_target_size(context)
        assert result.passed is False

    def test_check_target_size_zero(self) -> None:
        context = {"source_size": 1000, "target_size": 0}
        result = check_target_size(context)
        assert result.passed is False

    def test_check_not_mounted_clean(self) -> None:
        context = {"target_path": "/dev/sda1", "mounted_paths": ["/dev/sdb1"]}
        result = check_not_mounted(context)
        assert result.passed is True

    def test_check_not_mounted_is_mounted(self) -> None:
        context = {"target_path": "/dev/sda1", "mounted_paths": ["/dev/sda1"]}
        result = check_not_mounted(context)
        assert result.passed is False
