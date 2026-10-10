"""Database credentials from Secrets Manager (REM-01, REM-02).

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


class SecretCache:
    def __init__(self, region: str | None = None, client: Any = None) -> None:
        self._region = region
        self._client = client
        self._lock = threading.Lock()
        self._cache: dict[str, DbCredentials] = {}

    def _secrets_client(self) -> Any:
        if self._client is None:
            self._client = boto3.client("secretsmanager", region_name=self._region)
        return self._client

    def get(self, arn: str) -> DbCredentials:
        with self._lock:
            cached = self._cache.get(arn)
            if cached is not None:
                return cached
            response = self._secrets_client().get_secret_value(SecretId=arn)
            credentials = parse_db_secret(response["SecretString"])
            self._cache[arn] = credentials
            log.info("db_secret_loaded", user=credentials.username, host=credentials.host)
            return credentials

    def invalidate(self, arn: str) -> None:
        with self._lock:
            self._cache.pop(arn, None)
