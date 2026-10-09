import logging

from shiptrack.redact import REDACTED, RedactingFilter, redact, structlog_processor


def test_secret_looking_keys_are_replaced_at_any_depth() -> None:
    data = {
        "user": "app",
        "password": "hunter2",
        "nested": {"db_password": "x", "ok": 1},
        "list": [{"token": "t"}],
    }
    assert redact(data) == {
        "user": "app",
        "password": REDACTED,
        "nested": {"db_password": REDACTED, "ok": 1},
        "list": [{"token": REDACTED}],
    }


def test_the_original_is_not_changed() -> None:
    data = {"password": "hunter2"}
    redact(data)
    assert data == {"password": "hunter2"}


def test_the_structlog_processor_scrubs_the_event() -> None:
    event = {"event": "connecting", "password": "hunter2", "detail": {"secret": "s"}}
    cleaned = structlog_processor(None, "info", event)
    assert cleaned["password"] == REDACTED
    assert cleaned["detail"] == {"secret": REDACTED}
    assert cleaned["event"] == "connecting"


def test_the_stdlib_filter_scrubs_mapping_arguments() -> None:
    record = logging.LogRecord(
        "x", logging.INFO, __file__, 1, "%(password)s", ({"password": "hunter2"},), None
    )
    # LogRecord unwraps a single mapping argument itself.
    assert RedactingFilter().filter(record)
    assert record.args == {"password": REDACTED}
