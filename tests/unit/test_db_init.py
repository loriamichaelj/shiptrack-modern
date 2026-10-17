import pytest

from shiptrack.__main__ import main
from shiptrack.config import ConfigError, Settings


def test_the_admin_secret_is_named_per_cloud() -> None:
    assert Settings(cloud="aws", db_admin_secret_arn="arn:x").require_admin_secret() == "arn:x"
    assert (
        Settings(cloud="gcp", db_admin_secret_name="db-admin").require_admin_secret() == "db-admin"
    )


def test_a_missing_admin_secret_is_a_configuration_error() -> None:
    with pytest.raises(ConfigError, match="DB_ADMIN_SECRET_NAME"):
        Settings(cloud="gcp").require_admin_secret()
    with pytest.raises(ConfigError, match="DB_ADMIN_SECRET_ARN"):
        Settings(cloud="aws").require_admin_secret()


def test_db_init_without_settings_exits_with_the_configuration_error_code(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("SHIPTRACK_CLOUD", "gcp")
    monkeypatch.setenv("SHIPTRACK_GCP_PROJECT", "example-project")
    assert main(["db-init"]) == 2
    assert "DB_ADMIN_SECRET_NAME" in capsys.readouterr().err
