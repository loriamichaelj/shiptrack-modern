"""Integration fixtures: a throwaway Postgres database migrated with Alembic."""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import boto3
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import URL, make_url

from shiptrack.config import Settings
from shiptrack.events.worker import EventWorker
from shiptrack.main import create_app

ROOT = Path(__file__).resolve().parents[2]
ADMIN_URL = os.environ.get(
    "SHIPTRACK_TEST_DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/postgres"
)


def alembic_config() -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    return cfg


def migrate(url: URL, revision: str = "head", *, downgrade: bool = False) -> None:
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            cfg = alembic_config()
            cfg.attributes["connection"] = connection
            if downgrade:
                command.downgrade(cfg, revision)
            else:
                command.upgrade(cfg, revision)
            connection.commit()
    finally:
        engine.dispose()


def create_db_secret(url: URL, name: str | None = None) -> str:
    """Store the database's credentials in the emulated Secrets Manager; return the secret's ARN."""
    client = boto3.client("secretsmanager", region_name="us-east-1")
    secret = client.create_secret(
        Name=name or f"shiptrack/test/db/{uuid.uuid4().hex[:8]}",
        SecretString=json.dumps(
            {
                "username": url.username,
                "password": url.password,
                "host": url.host,
                "port": url.port or 5432,
                "dbname": url.database,
                "engine": "postgres",
            }
        ),
    )
    return str(secret["ARN"])


@dataclass(frozen=True)
class AwsResources:
    events_queue_url: str
    notify_queue_url: str
    bus_name: str
    pod_bucket: str


def create_aws_resources() -> AwsResources:
    """A fresh events queue, notifications queue, and event bus whose rule feeds the queue."""
    sqs = boto3.client("sqs", region_name="us-east-1")
    events = boto3.client("events", region_name="us-east-1")
    suffix = uuid.uuid4().hex[:8]
    events_queue = sqs.create_queue(QueueName=f"shiptrack-carrier-events-{suffix}")["QueueUrl"]
    notify_queue = sqs.create_queue(QueueName=f"shiptrack-notifications-{suffix}")["QueueUrl"]
    notify_arn = sqs.get_queue_attributes(QueueUrl=notify_queue, AttributeNames=["QueueArn"])[
        "Attributes"
    ]["QueueArn"]
    bus = f"shiptrack-{suffix}"
    events.create_event_bus(Name=bus)
    events.put_rule(
        Name="shiptrack-notify",
        EventBusName=bus,
        EventPattern=json.dumps(
            {
                "source": ["shiptrack.events"],
                "detail-type": ["ShipmentDelivered", "ShipmentException"],
            }
        ),
    )
    events.put_targets(
        Rule="shiptrack-notify",
        EventBusName=bus,
        Targets=[{"Id": "notifications", "Arn": notify_arn}],
    )
    pod_bucket = f"shiptrack-pod-{suffix}"
    boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=pod_bucket)
    return AwsResources(events_queue, notify_queue, bus, pod_bucket)


def settings_for(url: URL, aws: AwsResources | None = None) -> Settings:
    aws = aws or create_aws_resources()
    return Settings(
        db_secret_arn=create_db_secret(url),
        db_sslmode="disable",
        pod_bucket=aws.pod_bucket,
        events_queue_url=aws.events_queue_url,
        notify_queue_url=aws.notify_queue_url,
        event_bus_name=aws.bus_name,
        aws_region="us-east-1",
    )


@pytest.fixture(scope="session")
def admin_engine() -> Iterator[Engine]:
    engine = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def new_database(admin_engine: Engine) -> Iterator[Callable[[], URL]]:
    """Factory for empty databases; all of them are dropped at the end of the session."""
    created: list[str] = []

    def factory() -> URL:
        name = f"shiptrack_test_{uuid.uuid4().hex[:10]}"
        with admin_engine.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{name}"'))
        created.append(name)
        return make_url(ADMIN_URL).set(database=name)

    yield factory
    with admin_engine.connect() as connection:
        for name in created:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


@pytest.fixture(scope="session")
def database_url(new_database: Callable[[], URL]) -> URL:
    url = new_database()
    migrate(url)
    return url


@pytest.fixture(scope="session")
def engine(database_url: URL) -> Iterator[Engine]:
    engine = create_engine(database_url)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def clean_tables(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE shiptrack.sla_alerts, shiptrack.pod_documents, "
                "shiptrack.tracking_events, shiptrack.shipments RESTART IDENTITY CASCADE"
            )
        )


@pytest.fixture()
def settings(database_url: URL) -> Settings:
    return settings_for(database_url)


@pytest.fixture()
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def event_worker(client: TestClient) -> EventWorker:
    state = client.app.state  # type: ignore[attr-defined]
    return EventWorker(
        state.settings.events_queue_url,
        state.session_factory,
        bus_name=state.settings.event_bus_name,
        region="us-east-1",
        sleep=lambda _: None,
    )


def drain(client: TestClient) -> None:
    """Apply every event waiting in the queue, as worker-events would."""
    worker = event_worker(client)
    for _ in range(100):
        if worker.poll_once(0) == 0:
            return
    raise AssertionError("the events queue did not drain")


NOW = datetime.now(UTC)


def iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


@pytest.fixture()
def make_shipment(client: TestClient) -> Callable[..., dict[str, Any]]:
    def factory(
        carrier_code: str = "ACME", promised: datetime | None = None, **overrides: Any
    ) -> dict[str, Any]:
        body = {
            "carrier_code": carrier_code,
            "origin": "Rotterdam",
            "destination": "Chicago",
            "promised_delivery_at": iso(promised or NOW + timedelta(days=5)),
            **overrides,
        }
        response = client.post("/api/v1/shipments", json=body)
        assert response.status_code == 201, response.text
        return dict(response.json())

    return factory


@pytest.fixture()
def send_event(client: TestClient) -> Callable[..., Any]:
    def sender(
        shipment_id: str,
        event_type: str,
        occurred_at: datetime,
        *,
        key: str | None = None,
        location: str = "Hub",
        wait: bool = True,
    ) -> Any:
        response = client.post(
            f"/api/v1/shipments/{shipment_id}/events",
            headers={"Idempotency-Key": key or uuid.uuid4().hex},
            json={"event_type": event_type, "location": location, "occurred_at": iso(occurred_at)},
        )
        assert response.status_code == 202, response.text
        if wait:
            drain(client)
        return response

    return sender
