"""The message that carries a tracking event from the API to the worker (REM-06)."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from shiptrack.domain.status import Status
from shiptrack.events.processor import QueuedEvent


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


@dataclass(frozen=True)
class EventMessage:
    shipment_id: uuid.UUID
    idempotency_key: str
    event_type: Status
    location: str
    occurred_at: datetime
    payload: dict[str, Any] | None
    received_at: datetime
    request_id: str | None

    def to_json(self) -> str:
        return json.dumps(
            {
                "shipment_id": str(self.shipment_id),
                "idempotency_key": self.idempotency_key,
                "event_type": self.event_type.value,
                "location": self.location,
                "occurred_at": _iso(self.occurred_at),
                "payload": self.payload,
                "received_at": _iso(self.received_at),
                "request_id": self.request_id,
            },
            separators=(",", ":"),
        )

    @classmethod
    def from_json(cls, raw: str) -> EventMessage:
        data = json.loads(raw)
        return cls(
            shipment_id=uuid.UUID(data["shipment_id"]),
            idempotency_key=data["idempotency_key"],
            event_type=Status(data["event_type"]),
            location=data["location"],
            occurred_at=_parse(data["occurred_at"]),
            payload=data.get("payload"),
            received_at=_parse(data["received_at"]),
            request_id=data.get("request_id"),
        )

    def to_queued_event(self) -> QueuedEvent:
        return QueuedEvent(
            shipment_id=self.shipment_id,
            idempotency_key=self.idempotency_key,
            event_type=self.event_type,
            location=self.location,
            occurred_at=self.occurred_at,
            payload=self.payload,
        )
