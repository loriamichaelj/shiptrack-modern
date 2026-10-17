"""The JSON log shape: unchanged on AWS, with Cloud Logging's two extra fields on GCP."""

import json

import pytest
import structlog

from shiptrack.logconfig import configure_logging


def emit(capsys: pytest.CaptureFixture[str], cloud: str) -> dict[str, object]:
    configure_logging("INFO", cloud)
    structlog.get_logger("shiptrack.test").warning("something_happened", shipment="s1")
    return json.loads(capsys.readouterr().out.strip().splitlines()[-1])  # type: ignore[no-any-return]


def test_aws_records_have_no_cloud_logging_fields(capsys: pytest.CaptureFixture[str]) -> None:
    record = emit(capsys, "aws")
    assert record["event"] == "something_happened" and record["level"] == "warning"
    assert "severity" not in record and "message" not in record


def test_gcp_records_add_severity_and_message_and_keep_the_rest(
    capsys: pytest.CaptureFixture[str],
) -> None:
    record = emit(capsys, "gcp")
    assert record["severity"] == "WARNING" and record["message"] == "something_happened"
    assert record["event"] == "something_happened" and record["level"] == "warning"
    assert record["shipment"] == "s1" and record["logger"] == "shiptrack.test"
