"""
DiskForge structured logging.

Provides comprehensive logging with structured output for debugging
and audit trails of disk operations.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog
from structlog.types import EventDict, WrappedLogger

if TYPE_CHECKING:
    from diskforge.core.config import LoggingConfig


_configured = False


def add_timestamp(
    logger: WrappedLogger, method_name: str, event_dict: EventDict
) -> EventDict:
    """Add ISO format timestamp to log events."""
    event_dict["timestamp"] = datetime.now().isoformat()
    return event_dict


def add_log_level(
    logger: WrappedLogger, method_name: str, event_dict: EventDict
) -> EventDict:
    """Add log level to event dict."""
    event_dict["level"] = method_name.upper()
    return event_dict


def setup_logging(config: LoggingConfig) -> None:
    """Configure structured logging for DiskForge."""
    global _configured

    if _configured:
        return

    # Ensure log directory exists
    config.log_directory.mkdir(parents=True, exist_ok=True)

    # Set up standard logging handlers
    handlers: list[logging.Handler] = []

    if config.console_enabled:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(getattr(logging, config.level))
        handlers.append(console_handler)

    if config.file_enabled:
        log_file = config.log_directory / f"diskforge_{datetime.now().strftime('%Y%m%d')}.log"
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)  # Always log everything to file
        handlers.append(file_handler)

    # Configure root logger
    logging.basicConfig(
        level=logging.DEBUG,
        handlers=handlers,
        format="%(message)s",
    )

    # Set up structlog processors
    shared_processors: list[structlog.types.Processor] = [
        structlog.stdlib.add_logger_name,
        add_timestamp,
        add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if config.json_format:
        # JSON format for machine parsing
        structlog.configure(
            processors=shared_processors
            + [
                structlog.processors.format_exc_info,
                structlog.processors.JSONRenderer(),
            ],
            wrapper_class=structlog.stdlib.BoundLogger,
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )
    else:
        # Human-readable format
        structlog.configure(
            processors=shared_processors
            + [
                structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty()),
            ],
            wrapper_class=structlog.stdlib.BoundLogger,
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )

    _configured = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Get a structured logger instance."""
    return structlog.get_logger(name or "diskforge")


class OperationLogger:
    """Context manager for logging operations with start/end tracking."""

    def __init__(
        self,
        operation: str,
        logger: structlog.stdlib.BoundLogger | None = None,
        **context: Any,
    ):
        self.operation = operation
        self.logger = logger or get_logger()
        self.context = context
        self.start_time: datetime | None = None

    def __enter__(self) -> OperationLogger:
        self.start_time = datetime.now()
        self.logger.info(
            f"Starting {self.operation}",
            operation=self.operation,
            **self.context,
        )
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        duration = (datetime.now() - self.start_time).total_seconds() if self.start_time else 0

        if exc_type is not None:
            self.logger.error(
                f"Failed {self.operation}",
                operation=self.operation,
                duration_seconds=duration,
                error_type=exc_type.__name__,
                error=str(exc_val),
                **self.context,
            )
        else:
            self.logger.info(
                f"Completed {self.operation}",
                operation=self.operation,
                duration_seconds=duration,
                **self.context,
            )

    def update(self, **additional_context: Any) -> None:
        """Update the operation context."""
        self.context.update(additional_context)


class SessionLogger:
    """Logger that writes to both structlog and a session-specific file."""

    def __init__(self, session_file: Path, logger: structlog.stdlib.BoundLogger | None = None):
        self.session_file = session_file
        self.logger = logger or get_logger()
        self.entries: list[dict[str, Any]] = []
        self.session_file.parent.mkdir(parents=True, exist_ok=True)

    def log(self, level: str, message: str, **kwargs: Any) -> None:
        """Log to both structlog and session file."""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "level": level,
            "message": message,
            **kwargs,
        }
        self.entries.append(entry)

        # Also log to structlog
        log_method = getattr(self.logger, level.lower(), self.logger.info)
        log_method(message, **kwargs)

    def info(self, message: str, **kwargs: Any) -> None:
        self.log("INFO", message, **kwargs)

    def warning(self, message: str, **kwargs: Any) -> None:
        self.log("WARNING", message, **kwargs)

    def error(self, message: str, **kwargs: Any) -> None:
        self.log("ERROR", message, **kwargs)

    def debug(self, message: str, **kwargs: Any) -> None:
        self.log("DEBUG", message, **kwargs)

    def save(self) -> None:
        """Save session log to file."""
        import json

        with open(self.session_file, "w") as f:
            json.dump(
                {
                    "session_file": str(self.session_file),
                    "entries": self.entries,
                    "summary": {
                        "total_entries": len(self.entries),
                        "errors": sum(1 for e in self.entries if e["level"] == "ERROR"),
                        "warnings": sum(1 for e in self.entries if e["level"] == "WARNING"),
                    },
                },
                f,
                indent=2,
            )
