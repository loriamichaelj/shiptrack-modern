"""`python -m shiptrack <command>`: one image, five roles (design 5.12)."""

import pytest

from shiptrack import __main__ as entrypoint


def test_the_commands_are_the_designs_five() -> None:
    assert entrypoint.COMMANDS == ("api", "worker-events", "worker-notify", "sla-scan", "migrate")


def test_the_ports_are_fixed() -> None:
    assert (entrypoint.API_PORT, entrypoint.OPS_PORT) == (8000, 9090)


def test_an_unknown_command_is_rejected() -> None:
    with pytest.raises(SystemExit) as exit_info:
        entrypoint.main(["bogus"])
    assert exit_info.value.code == 2


def test_a_missing_setting_is_a_clean_exit_not_a_traceback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("SHIPTRACK_EVENTS_QUEUE_URL", raising=False)
    monkeypatch.delenv("SHIPTRACK_DB_SECRET_ARN", raising=False)
    assert entrypoint.main(["worker-events"]) == 2
    assert "SHIPTRACK_" in capsys.readouterr().err


def test_migrate_refuses_until_migrations_are_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHIPTRACK_DB_MIGRATOR_SECRET_ARN", "arn:aws:secretsmanager:x:1:secret:y")
    monkeypatch.delenv("SHIPTRACK_MIGRATIONS_ENABLED", raising=False)
    assert entrypoint.main(["migrate"]) == 2
