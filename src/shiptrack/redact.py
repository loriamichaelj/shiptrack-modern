"""Keep secret values out of the logs (REM-01).

Anything under a key whose name looks like a credential is replaced before it is logged. The same
function backs the structlog processor and the stdlib logging filter.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, MutableMapping
from typing import Any

REDACTED = "***"
SECRET_KEYS = ("password", "passwd", "secret", "token", "authorization", "api_key", "apikey")


def is_secret_key(key: object) -> bool:
    name = str(key).lower()
    return any(part in name for part in SECRET_KEYS)


def redact(value: Any) -> Any:
    """A copy of `value` with the values of secret-looking keys replaced, at any depth."""
    if isinstance(value, Mapping):
        return {k: REDACTED if is_secret_key(k) else redact(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return type(value)(redact(v) for v in value)
    return value


def structlog_processor(
    _: Any, __: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    for key in list(event_dict):
        if is_secret_key(key):
            event_dict[key] = REDACTED
        else:
            event_dict[key] = redact(event_dict[key])
    return event_dict


class RedactingFilter(logging.Filter):
    """For records that did not come through structlog: scrub mapping arguments."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, Mapping):
            record.args = redact(record.args)
        return True
