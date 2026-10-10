"""Structured JSON logs on stdout (REM-08).

Every record carries `ts`, `level`, `event`, and `logger`, plus whatever context is bound, such as
the request's `request_id`. structlog and the standard library share one pipeline, so the logs of
uvicorn, SQLAlchemy, and boto3 come out in the same shape. Secret-looking keys are redacted.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from shiptrack import redact

_HANDLER_MARK = "_shiptrack_handler"


def _shared_processors() -> list[Any]:
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True, key="ts"),
        redact.structlog_processor,
        structlog.processors.format_exc_info,
    ]


def configure_logging(level: str = "INFO") -> None:
    shared = _shared_processors()
    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            # Drop the formatter's own bookkeeping keys, then render one JSON object per line.
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.JSONRenderer(),
            ],
            foreign_pre_chain=shared,
        )
    )
    setattr(handler, _HANDLER_MARK, True)
    handler.addFilter(redact.RedactingFilter())

    root = logging.getLogger()
    # Replace only our own handler from an earlier call; leave any other (a test's, for instance).
    for existing in [h for h in root.handlers if getattr(h, _HANDLER_MARK, False)]:
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level)
    # uvicorn's access log is replaced by the request middleware, which also drops health checks.
    logging.getLogger("uvicorn.access").disabled = True
    logging.getLogger("botocore").setLevel(max(logging.getLevelName(level), logging.WARNING))
    logging.getLogger("boto3").setLevel(max(logging.getLevelName(level), logging.WARNING))
