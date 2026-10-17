"""Structured JSON logs on stdout (REM-08).

Every record carries `ts`, `level`, `event`, and `logger`, plus whatever context is bound, such as
the request's `request_id`. structlog and the standard library share one pipeline, so the logs of
uvicorn, SQLAlchemy, and the cloud SDKs come out in the same shape. Secret-looking keys are
redacted. On GCP every record also carries `severity` and `message`, which Cloud Logging reads as
the level and the text; the other fields are unchanged.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from shiptrack import redact

_HANDLER_MARK = "_shiptrack_handler"


def _cloud_logging_fields(_: Any, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    event_dict["severity"] = str(event_dict.get("level", "info")).upper()
    event_dict["message"] = event_dict.get("event", "")
    return event_dict


def _shared_processors(cloud: str) -> list[Any]:
    extra = [_cloud_logging_fields] if cloud == "gcp" else []
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True, key="ts"),
        redact.structlog_processor,
        structlog.processors.format_exc_info,
        *extra,
    ]


def configure_logging(level: str = "INFO", cloud: str = "aws") -> None:
    shared = _shared_processors(cloud)
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
    for name in ("google", "urllib3", "grpc"):
        logging.getLogger(name).setLevel(max(logging.getLevelName(level), logging.WARNING))
