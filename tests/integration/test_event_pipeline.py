"""REM-06 end to end against the emulated SQS and EventBridge."""

import json
import uuid
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import boto3
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from shiptrack.config import Settings
from shiptrack.events import worker as worker_module
from shiptrack.events.worker import NotifyWorker

from .conftest import NOW, drain, event_worker, iso

MakeShipment = Callable[..., dict[str, Any]]


def sqs() -> Any:
    return boto3.client("sqs", region_name="us-east-1")


def post(client: TestClient, shipment_id: str, key: str, event_type: str = "PICKED_UP") -> Any:
    return client.post(
        f"/api/v1/shipments/{shipment_id}/events",
        headers={"Idempotency-Key": key},
        json={
            "event_type": event_type,
            "location": "Hub",
            "occurred_at": iso(NOW - timedelta(hours=1)),
        },
    )


def stored_events(engine: Engine) -> int:
    with engine.connect() as connection:
        return int(connection.scalar(text("SELECT count(*) FROM shiptrack.tracking_events")) or 0)


def test_the_api_queues_the_event_and_does_not_apply_it(
    client: TestClient, settings: Settings, engine: Engine, make_shipment: MakeShipment
) -> None:
    shipment = make_shipment()
    assert post(client, shipment["id"], "k-1").status_code == 202
    assert stored_events(engine) == 0  # accepted, not yet applied: the worker does that

    received = sqs().receive_message(
        QueueUrl=settings.events_queue_url, MessageAttributeNames=["All"], MaxNumberOfMessages=10
    )["Messages"]
    assert len(received) == 1
    body = json.loads(received[0]["Body"])
    assert body["idempotency_key"] == "k-1"
    assert body["shipment_id"] == shipment["id"]
    assert body["event_type"] == "PICKED_UP"
    assert body["received_at"].endswith("Z")
    assert received[0]["MessageAttributes"]["idempotency_key"]["StringValue"] == "k-1"


def test_the_worker_applies_what_the_api_queued(
    client: TestClient, engine: Engine, make_shipment: MakeShipment
) -> None:
    shipment = make_shipment()
    post(client, shipment["id"], "k-1")
    drain(client)
    assert stored_events(engine) == 1
    view = client.get(f"/api/v1/track/{shipment['tracking_number']}").json()
    assert view["status"] == "PICKED_UP"


def test_an_event_that_cannot_be_queued_is_a_503_and_is_never_acknowledged(
    client: TestClient, settings: Settings, engine: Engine, make_shipment: MakeShipment
) -> None:
    shipment = make_shipment()
    sqs().delete_queue(QueueUrl=settings.events_queue_url)
    response = post(client, shipment["id"], "k-1")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "QUEUE_UNAVAILABLE"
    assert stored_events(engine) == 0


def test_an_unknown_shipment_is_still_a_404_and_queues_nothing(
    client: TestClient, settings: Settings
) -> None:
    assert post(client, str(uuid.uuid4()), "k-1").status_code == 404
    assert "Messages" not in sqs().receive_message(QueueUrl=settings.events_queue_url)


def test_the_same_key_sent_twice_is_applied_once(
    client: TestClient, engine: Engine, make_shipment: MakeShipment
) -> None:
    shipment = make_shipment()
    assert post(client, shipment["id"], "same").status_code == 202
    assert post(client, shipment["id"], "same").status_code == 202
    drain(client)
    assert stored_events(engine) == 1


def test_a_failed_apply_leaves_the_message_for_redelivery(
    client: TestClient,
    settings: Settings,
    engine: Engine,
    make_shipment: MakeShipment,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shipment = make_shipment()
    post(client, shipment["id"], "k-1")

    def broken(*_: Any) -> None:
        raise RuntimeError("database down")

    with monkeypatch.context() as patch:
        patch.setattr(worker_module, "apply_event", broken)
        assert event_worker(client).poll_once(0) == 1
    assert stored_events(engine) == 0

    # The message is hidden for the visibility timeout; making it visible again simulates the wait.
    attrs = sqs().get_queue_attributes(
        QueueUrl=settings.events_queue_url, AttributeNames=["ApproximateNumberOfMessagesNotVisible"]
    )["Attributes"]
    assert attrs["ApproximateNumberOfMessagesNotVisible"] == "1"


def test_delivered_and_exception_reach_the_notifications_queue(
    client: TestClient, settings: Settings, make_shipment: MakeShipment
) -> None:
    delivered = make_shipment()
    post(client, delivered["id"], "d-1", "DELIVERED")
    excepted = make_shipment()
    post(client, excepted["id"], "e-1", "EXCEPTION")
    post(client, make_shipment()["id"], "p-1", "PICKED_UP")  # not announced
    drain(client)

    messages = sqs().receive_message(
        QueueUrl=settings.notify_queue_url, MaxNumberOfMessages=10, WaitTimeSeconds=0
    )["Messages"]
    envelopes = [json.loads(m["Body"]) for m in messages]
    assert sorted(e["detail-type"] for e in envelopes) == ["ShipmentDelivered", "ShipmentException"]
    delivered_detail = next(e for e in envelopes if e["detail-type"] == "ShipmentDelivered")[
        "detail"
    ]
    assert delivered_detail["event_id"] == "d-1"
    assert delivered_detail["tracking_number"] == delivered["tracking_number"]
    assert delivered_detail["status"] == "DELIVERED"


def test_the_notifier_consumes_the_envelope_eventbridge_writes(
    client: TestClient, settings: Settings, make_shipment: MakeShipment
) -> None:
    shipment = make_shipment()
    post(client, shipment["id"], "d-1", "DELIVERED")
    drain(client)
    assert settings.notify_queue_url
    notifier = NotifyWorker(settings.notify_queue_url, "us-east-1")
    assert notifier.poll_once(0) == 1
    remaining = sqs().get_queue_attributes(
        QueueUrl=settings.notify_queue_url, AttributeNames=["ApproximateNumberOfMessages"]
    )["Attributes"]["ApproximateNumberOfMessages"]
    assert remaining == "0"
