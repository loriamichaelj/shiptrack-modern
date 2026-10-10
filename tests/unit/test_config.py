import pytest
from pydantic import ValidationError

from shiptrack.config import ConfigError, Settings


def settings(**env: str) -> Settings:
    return Settings(_env_file=None, **env)  # type: ignore[arg-type]


def test_defaults_need_no_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("SHIPTRACK_LOG_LEVEL", "SHIPTRACK_DB_POOL_SIZE", "SHIPTRACK_FAULT_ERROR_RATE"):
        monkeypatch.delenv(name, raising=False)
    s = Settings()
    assert s.log_level == "INFO"
    assert (s.db_pool_size, s.db_max_overflow) == (4, 2)
    assert s.fault_error_rate == 0.0
    assert s.fault_ready_fail is False
    assert s.migrations_enabled is False
    assert s.schema_compat_revisions == frozenset({"0001"})


def test_values_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHIPTRACK_DB_SECRET_ARN", "arn:aws:secretsmanager:us-east-1:1:secret:app")
    monkeypatch.setenv("SHIPTRACK_EVENTS_QUEUE_URL", "http://queue.test/events")
    monkeypatch.setenv("SHIPTRACK_DB_POOL_SIZE", "7")
    monkeypatch.setenv("SHIPTRACK_LOG_LEVEL", "debug")
    monkeypatch.setenv("AWS_REGION", "eu-west-1")
    s = Settings()
    assert s.require_db_secret().endswith(":app")
    assert s.events_queue_url == "http://queue.test/events"
    assert s.db_pool_size == 7
    assert s.log_level == "DEBUG"
    assert s.aws_region == "eu-west-1"


def test_the_ini_file_and_its_variable_are_gone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHIPTRACK_CONFIG", "/etc/shiptrack/app.ini")
    assert not hasattr(Settings(), "config")
    assert not hasattr(Settings(), "db_password")


def test_a_missing_secret_arn_is_a_clear_error() -> None:
    with pytest.raises(ConfigError, match="SHIPTRACK_DB_SECRET_ARN"):
        Settings(db_secret_arn=None).require_db_secret()
    with pytest.raises(ConfigError, match="MIGRATOR_SECRET_ARN"):
        Settings(db_migrator_secret_arn=None).require_migrator_secret()


def test_schema_compat_is_a_comma_separated_list() -> None:
    assert Settings(schema_compat="0001, 0002 ,").schema_compat_revisions == {"0001", "0002"}


@pytest.mark.parametrize("rate", [-0.1, 1.5])
def test_the_fault_rate_is_a_probability(rate: float) -> None:
    with pytest.raises(ValidationError):
        Settings(fault_error_rate=rate)


def test_an_unknown_log_level_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(log_level="LOUD")


@pytest.mark.parametrize(
    ("base_url", "expected"),
    [("https://shiptrack.example.test", True), ("http://alb.example.test", False), ("", False)],
)
def test_hsts_only_when_the_base_url_is_https(base_url: str, expected: bool) -> None:
    assert Settings(base_url=base_url).hsts_enabled is expected
