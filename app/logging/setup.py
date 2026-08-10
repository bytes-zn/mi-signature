"""Structured logging configuration based on structlog.

Produces JSON log lines in non-development environments and a colored
console output when ``log_format`` is set to ``console``. Request-scoped
context (e.g. the request ID) is attached via structlog contextvars.
"""

import logging
import sys
from typing import Literal

import structlog


def configure_logging(
    log_level: str = "INFO",
    log_format: Literal["json", "console"] = "json",
) -> None:
    """Configure stdlib logging and structlog for the current process.

    Args:
        log_level: Standard logging level name (e.g. ``INFO``, ``DEBUG``).
        log_format: ``json`` for machine-readable output, ``console`` for humans.
    """
    level = getattr(logging, log_level.upper(), logging.INFO)

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    renderer: structlog.types.Processor
    if log_format == "console":
        renderer = structlog.dev.ConsoleRenderer()
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[*shared_processors, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # Tame noisy third-party loggers.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
