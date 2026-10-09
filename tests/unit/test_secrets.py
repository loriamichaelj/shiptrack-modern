import json

import pytest

from shiptrack.secrets import DbCredentials, SecretCache, parse_db_secret

SECRET = json.dumps(
    {
        "username": "shiptrack_app",
        "password": "pw",
        "host": "db.test",
        "port": 5432,
        "dbname": "shiptrack",
        "engine": "postgres",
    }
)


class FakeClient:
    def __init__(self, *values: str) -> None:
        self.values = list(values)
        self.calls: list[str] = []

    def get_secret_value(self, SecretId: str) -> dict[str, str]:
        self.calls.append(SecretId)
        return {"SecretString": self.values.pop(0) if len(self.values) > 1 else self.values[0]}


def test_the_secret_is_parsed_into_credentials() -> None:
    credentials = parse_db_secret(SECRET)
    assert credentials == DbCredentials("db.test", 5432, "shiptrack", "shiptrack_app", "pw")


def test_a_secret_without_a_password_is_rejected() -> None:
    with pytest.raises(ValueError, match="password"):
        parse_db_secret(json.dumps({"username": "u", "host": "h", "dbname": "d"}))


def test_the_password_is_never_in_the_repr() -> None:
    assert "pw" not in repr(parse_db_secret(SECRET))


def test_the_secret_is_fetched_once_and_cached() -> None:
    client = FakeClient(SECRET)
    cache = SecretCache(client=client)
    cache.get("arn:app")
    cache.get("arn:app")
    assert client.calls == ["arn:app"]


def test_invalidating_fetches_again() -> None:
    rotated = SECRET.replace('"pw"', '"new-pw"')
    client = FakeClient(SECRET, rotated)
    cache = SecretCache(client=client)
    assert cache.get("arn:app").password == "pw"
    cache.invalidate("arn:app")
    assert cache.get("arn:app").password == "new-pw"
    assert len(client.calls) == 2
