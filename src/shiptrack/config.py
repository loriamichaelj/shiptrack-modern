"""Configuration from environment variables (REM-01).

Nothing is read from a file and no credential is configured here: the database credentials are
fetched from Secrets Manager at startup (see `shiptrack.secrets`).
"""

from __future__ import annotations

import logging
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigError(Exception):
    """A setting that a command needs is missing."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SHIPTRACK_", extra="ignore")

    # Credentials: the ARN of the secret, never the secret itself.
    db_secret_arn: str | None = None
    db_migrator_secret_arn: str | None = None
    db_sslmode: str = "require"

    # Connection pool, set per workload in Helm (design 5.10).
    db_pool_size: int = Field(default=4, ge=1)
    db_max_overflow: int = Field(default=2, ge=0)

    # AWS resources.
    events_queue_url: str | None = None
    notify_queue_url: str | None = None
    event_bus_name: str | None = None
    pod_bucket: str | None = None
    # Removed with the local storage in REM-05.
    pod_dir: Path = Path("/var/lib/shiptrack/pod")
    aws_region: str | None = Field(default=None, validation_alias="AWS_REGION")

    # Alembic revisions this build tolerates (design 9.1). /readyz fails when the database is at
    # any other revision.
    schema_compat: str = "0001"

    log_level: str = "INFO"

    # Whether `migrate` may run. It stays off until schema ownership is handed over (design 9.1).
    migrations_enabled: bool = False

    # Where the built UI is baked into the image.
    web_dist: Path = Path("/app/web/dist")

    # The platform base URL decides whether to send Strict-Transport-Security.
    base_url: str = ""

    # Game days only (design 5.9).
    fault_error_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    fault_ready_fail: bool = False

    @field_validator("log_level")
    @classmethod
    def _upper(cls, value: str) -> str:
        level = value.upper()
        if level not in logging.getLevelNamesMapping():
            raise ValueError(f"unknown log level: {value}")
        return level

    @property
    def schema_compat_revisions(self) -> frozenset[str]:
        return frozenset(part.strip() for part in self.schema_compat.split(",") if part.strip())

    @property
    def hsts_enabled(self) -> bool:
        return self.base_url.lower().startswith("https://")

    def require_db_secret(self) -> str:
        if not self.db_secret_arn:
            raise ConfigError("SHIPTRACK_DB_SECRET_ARN is required")
        return self.db_secret_arn

    def require_events_queue(self) -> str:
        if not self.events_queue_url:
            raise ConfigError("SHIPTRACK_EVENTS_QUEUE_URL is required")
        return self.events_queue_url

    def require_notify_queue(self) -> str:
        if not self.notify_queue_url:
            raise ConfigError("SHIPTRACK_NOTIFY_QUEUE_URL is required")
        return self.notify_queue_url

    def require_migrator_secret(self) -> str:
        if not self.db_migrator_secret_arn:
            raise ConfigError("SHIPTRACK_DB_MIGRATOR_SECRET_ARN is required")
        return self.db_migrator_secret_arn


def load_settings() -> Settings:
    return Settings()
