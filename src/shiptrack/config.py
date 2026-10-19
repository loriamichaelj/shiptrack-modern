"""Configuration from environment variables (REM-01).

Nothing is read from a file and no credential is configured here: the database credentials are
fetched from the cloud's secret store at startup (see `shiptrack.secrets`).

`SHIPTRACK_CLOUD` picks the cloud (ADR-0032). Each cloud has its own block of settings, and a block
is checked only when its cloud is selected, at the point a command needs it.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigError(Exception):
    """A setting that a command needs is missing."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SHIPTRACK_", extra="ignore")

    cloud: Literal["aws", "gcp"] = "aws"
    # The region this deployment runs in, sent as X-ShipTrack-Region (ADR-0039). On AWS, AWS_REGION
    # is used when it is unset.
    region: str | None = Field(default=None, pattern=r"^[a-z0-9-]{1,40}$")

    # Credentials: the ARN of the secret, never the secret itself.
    db_secret_arn: str | None = None
    db_migrator_secret_arn: str | None = None
    db_admin_secret_arn: str | None = None
    db_sslmode: str = "require"

    # db-init: the SQL it runs, and the most connections each role may hold.
    db_init_sql: Path = Path("/app/db/init.sql")
    db_app_connection_limit: int = Field(default=200, ge=1)
    db_migrator_connection_limit: int = Field(default=150, ge=1)

    # Connection pool, set per workload in Helm (design 5.10).
    db_pool_size: int = Field(default=4, ge=1)
    db_max_overflow: int = Field(default=2, ge=0)

    # AWS resources.
    events_queue_url: str | None = None
    notify_queue_url: str | None = None
    event_bus_name: str | None = None
    pod_bucket: str | None = None
    aws_region: str | None = Field(default=None, validation_alias="AWS_REGION")

    # GCP resources. The secret names are short: the project comes from `gcp_project`.
    gcp_project: str | None = None
    db_secret_name: str | None = None
    db_migrator_secret_name: str | None = None
    db_admin_secret_name: str | None = None
    events_topic: str | None = None
    events_subscription: str | None = None
    notify_topic: str | None = None
    notify_subscription: str | None = None
    proof_of_delivery_bucket: str | None = None
    proof_of_delivery_signer: str | None = None

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
    def serving_region(self) -> str | None:
        if self.region:
            return self.region
        return self.aws_region if self.cloud == "aws" else None

    @property
    def hsts_enabled(self) -> bool:
        return self.base_url.lower().startswith("https://")

    def _require(self, value: str | None, variable: str) -> str:
        if not value:
            raise ConfigError(f"SHIPTRACK_{variable} is required when SHIPTRACK_CLOUD={self.cloud}")
        return value

    def _pick(self, aws: tuple[str | None, str], gcp: tuple[str | None, str]) -> str:
        value, variable = aws if self.cloud == "aws" else gcp
        return self._require(value, variable)

    def require_db_secret(self) -> str:
        return self._pick(
            (self.db_secret_arn, "DB_SECRET_ARN"), (self.db_secret_name, "DB_SECRET_NAME")
        )

    def require_migrator_secret(self) -> str:
        return self._pick(
            (self.db_migrator_secret_arn, "DB_MIGRATOR_SECRET_ARN"),
            (self.db_migrator_secret_name, "DB_MIGRATOR_SECRET_NAME"),
        )

    def require_admin_secret(self) -> str:
        return self._pick(
            (self.db_admin_secret_arn, "DB_ADMIN_SECRET_ARN"),
            (self.db_admin_secret_name, "DB_ADMIN_SECRET_NAME"),
        )

    def require_events_destination(self) -> str:
        """Where the API sends events: the SQS queue URL, or the Pub/Sub topic."""
        return self._pick(
            (self.events_queue_url, "EVENTS_QUEUE_URL"), (self.events_topic, "EVENTS_TOPIC")
        )

    def require_events_source(self) -> str:
        """What worker-events reads: the SQS queue URL, or the Pub/Sub subscription."""
        return self._pick(
            (self.events_queue_url, "EVENTS_QUEUE_URL"),
            (self.events_subscription, "EVENTS_SUBSCRIPTION"),
        )

    def require_notify_source(self) -> str:
        """What worker-notify reads: the SQS queue URL, or the Pub/Sub subscription."""
        return self._pick(
            (self.notify_queue_url, "NOTIFY_QUEUE_URL"),
            (self.notify_subscription, "NOTIFY_SUBSCRIPTION"),
        )

    def require_pod_bucket(self) -> str:
        return self._pick(
            (self.pod_bucket, "POD_BUCKET"),
            (self.proof_of_delivery_bucket, "PROOF_OF_DELIVERY_BUCKET"),
        )

    def require_gcp_project(self) -> str:
        return self._require(self.gcp_project, "GCP_PROJECT")

    def require_proof_of_delivery_signer(self) -> str:
        return self._require(self.proof_of_delivery_signer, "PROOF_OF_DELIVERY_SIGNER")


def load_settings() -> Settings:
    return Settings()
