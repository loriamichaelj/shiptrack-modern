import json
import uuid
from datetime import UTC, datetime

from shiptrack.domain.status import Status
from shiptrack.events.messages import EventMessage

SHIPMENT = uuid.UUID("11111111-2222-3333-4444-55555555555a")


def message(**overrides: object) -> EventMessage:
    base: dict[str, object] = {
        "shipment_id": SHIPMENT,
        "idempotency_key": "key-1",
        "event_type": Status.IN_TRANSIT,
        "location": "Rotterdam",
        "occurred_at": datetime(2026, 10, 1, 12, 0, tzinfo=UTC),
        "payload": {"gate": 4},
        "received_at": datetime(2026, 10, 1, 12, 0, 5, tzinfo=UTC),
        "request_id": "req-1",
    }
    base.update(overrides)
    return EventMessage(**base)  # type: ignore[arg-type]


def test_the_body_has_the_fields_in_the_design() -> None:
    body = json.loads(message().to_json())
    assert set(body) == {
        "shipment_id",
        "idempotency_key",
        "event_type",
        "location",
        "occurred_at",
        "payload",
        "received_at",
        "request_id",
    }
    assert body["occurred_at"] == "2026-10-01T12:00:00Z"
    assert body["event_type"] == "IN_TRANSIT"


def test_a_message_survives_a_round_trip() -> None:
    original = message()
    assert EventMessage.from_json(original.to_json()) == original


def test_a_missing_payload_and_request_id_are_fine() -> None:
    original = message(payload=None, request_id=None)
    assert EventMessage.from_json(original.to_json()) == original


def test_it_converts_to_the_event_the_database_code_applies() -> None:
    queued = message().to_queued_event()
    assert queued.shipment_id == SHIPMENT
    assert queued.idempotency_key == "key-1"
    assert queued.event_type is Status.IN_TRANSIT
