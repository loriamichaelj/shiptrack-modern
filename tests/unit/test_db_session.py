"""The pool's connection function refetches the secret once when the server turns the login down."""

import json
from collections.abc import Sequence
from typing import Any

import psycopg
import pytest
from psycopg import errors as pg_errors

from shiptrack.config import Settings
from shiptrack.db import session
from shiptrack.db.session import make_creator
from shiptrack.secrets import SecretCache


def secret(password: str) -> str:
    return json.dumps(
        {
            "username": "shiptrack_app",
            "password": password,
            "host": "db.test",
            "port": 5432,
            "dbname": "shiptrack",
            "engine": "postgres",
        }
    )


class Rotating:
    """A secret store whose value changes after the first fetch, as a rotation does."""

    def __init__(self) -> None:
        self.versions = [secret("old"), secret("new")]
        self.fetches = 0

    def fetch(self, name: str) -> str:
        value = self.versions[min(self.fetches, len(self.versions) - 1)]
        self.fetches += 1
        return value


def creator_with(
    monkeypatch: pytest.MonkeyPatch, failures: Sequence[Exception]
) -> tuple[Any, Rotating, list[str]]:
    """A creator whose connections fail with `failures` in turn, then succeed."""
    pending = list(failures)
    store = Rotating()
    used: list[str] = []

    def connect(credentials: Any, sslmode: str) -> str:
        used.append(credentials.password)
        if pending:
            raise pending.pop(0)
        return "connection"

    monkeypatch.setattr(session, "_connect", connect)
    creator = make_creator(Settings(), "shiptrack-db-app", SecretCache(source=store))
    return creator, store, used


def test_a_login_rejected_while_connecting_is_retried_with_the_new_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # How libpq reports a rejected login: a plain OperationalError with the FATAL text.
    rejected = psycopg.OperationalError(
        'connection failed: connection to server at "10.0.0.1", port 5432 failed: FATAL:  '
        'password authentication failed for user "shiptrack_app"'
    )
    creator, store, used = creator_with(monkeypatch, [rejected])
    assert creator() == "connection"
    assert used == ["old", "new"]
    assert store.fetches == 2


@pytest.mark.parametrize(
    "error", [pg_errors.InvalidPassword, pg_errors.InvalidAuthorizationSpecification]
)
def test_the_classes_for_the_sqlstate_still_count(
    monkeypatch: pytest.MonkeyPatch, error: type
) -> None:
    creator, _, used = creator_with(monkeypatch, [error("rejected")])
    assert creator() == "connection"
    assert used == ["old", "new"]


def test_a_database_that_is_down_is_not_a_reason_to_fetch_the_secret_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    down = psycopg.OperationalError("connection failed: connection refused")
    creator, store, used = creator_with(monkeypatch, [down])
    with pytest.raises(psycopg.OperationalError, match="connection refused"):
        creator()
    assert used == ["old"]
    assert store.fetches == 1


def test_a_second_rejection_is_raised_and_not_retried_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rejected = [
        psycopg.OperationalError('FATAL:  password authentication failed for user "shiptrack_app"')
        for _ in range(2)
    ]
    creator, store, used = creator_with(monkeypatch, rejected)
    with pytest.raises(psycopg.OperationalError, match="password authentication failed"):
        creator()
    assert used == ["old", "new"]
    assert store.fetches == 2
