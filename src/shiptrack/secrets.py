"""Database credentials from the cloud's secret store (REM-01, REM-02).

The secret is fetched when it is first needed and kept in memory only. After an authentication
failure the cache entry is dropped and the secret is fetched once more, so a rotated password is
picked up without a restart.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from typing import Any

import boto3
import structlog

from shiptrack.ports import SecretSource

log = structlog.get_logger("shiptrack.secrets")


@dataclass(frozen=True)
class DbCredentials:
    host: str
    port: int
    dbname: str
    username: str
    password: str = ""

    def __repr__(self) -> str:  # never show the password, even by accident
        return (
            f"DbCredentials(host={self.host!r}, port={self.port}, "
            f"dbname={self.dbname!r}, username={self.username!r})"
        )


def parse_db_secret(raw: str) -> DbCredentials:
    data: dict[str, Any] = json.loads(raw)
    try:
        return DbCredentials(
            host=str(data["host"]),
            port=int(data.get("port", 5432)),
            dbname=str(data["dbname"]),
            username=str(data["username"]),
            password=str(data["password"]),
        )
    except KeyError as exc:
        raise ValueError(f"the database secret has no '{exc.args[0]}' key") from exc


class AwsSecretSource:
    """Secrets Manager. `name` is the secret's ARN."""

    def __init__(self, region: str | None = None, client: Any = None) -> None:
        self._region = region
        self._client = client

    def fetch(self, name: str) -> str:
        if self._client is None:
            self._client = boto3.client("secretsmanager", region_name=self._region)
        return str(self._client.get_secret_value(SecretId=name)["SecretString"])


class SecretCache:
    def __init__(
        self, region: str | None = None, client: Any = None, source: SecretSource | None = None
    ) -> None:
        self._source = source or AwsSecretSource(region, client)
        self._lock = threading.Lock()
        self._cache: dict[str, DbCredentials] = {}

    def get(self, name: str) -> DbCredentials:
        with self._lock:
            cached = self._cache.get(name)
            if cached is not None:
                return cached
            credentials = parse_db_secret(self._source.fetch(name))
            self._cache[name] = credentials
            log.info("db_secret_loaded", user=credentials.username, host=credentials.host)
            return credentials

    def invalidate(self, name: str) -> None:
        with self._lock:
            self._cache.pop(name, None)
