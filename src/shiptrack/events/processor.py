"""Applying one event to the database (legacy design 3.3)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from shiptrack.db.models import Shipment, TrackingEvent
from shiptrack.domain.eta import estimate_delivery
from shiptrack.domain.status import Outcome, Status, decide

log = structlog.get_logger("shiptrack.events")


@dataclass(frozen=True)
class QueuedEvent:
    shipment_id: uuid.UUID
    idempotency_key: str
    event_type: Status
    location: str
    occurred_at: datetime
    payload: dict[str, Any] | None


class ApplyResult(StrEnum):
    APPLIED = "APPLIED"
    DUPLICATE = "DUPLICATE"
    OUT_OF_ORDER = "OUT_OF_ORDER"
    INVALID = "INVALID"


def apply_event(session: Session, event: QueuedEvent) -> ApplyResult:
    """Apply one event in a single transaction (legacy design §3.3)."""
    # 1. Insert the event; a conflict on idempotency_key means it is a duplicate.
    insert = (
        pg_insert(TrackingEvent)
        .values(
            shipment_id=event.shipment_id,
            event_type=event.event_type.value,
            location=event.location,
            occurred_at=event.occurred_at,
            idempotency_key=event.idempotency_key,
            applied=False,
            payload=event.payload,
        )
        .on_conflict_do_nothing(index_elements=[TrackingEvent.idempotency_key])
        .returning(TrackingEvent.id)
    )
    event_id = session.execute(insert).scalar_one_or_none()
    if event_id is None:
        session.rollback()
        return ApplyResult.DUPLICATE

    # Lock the shipment so concurrent events for it are applied one at a time.
    shipment = session.execute(
        select(Shipment).where(Shipment.id == event.shipment_id).with_for_update()
    ).scalar_one()

    # 2 and 3. Out-of-order and invalid events are stored but do not change the shipment.
    outcome = decide(
        Status(shipment.status), shipment.last_event_at, event.event_type, event.occurred_at
    )
    if outcome is Outcome.OUT_OF_ORDER:
        session.commit()
        return ApplyResult.OUT_OF_ORDER
    if outcome is Outcome.INVALID:
        log.warning(
            "invalid_transition_ignored",
            shipment_id=str(shipment.id),
            from_status=shipment.status,
            to_status=event.event_type.value,
            idempotency_key=event.idempotency_key,
        )
        session.commit()
        return ApplyResult.INVALID

    # 4. Applied: update status, last_event_at, ETA, and delivered_at.
    changes: dict[str, Any] = {
        "status": event.event_type.value,
        "last_event_at": event.occurred_at,
        "estimated_delivery_at": estimate_delivery(
            event.event_type,
            event.occurred_at,
            shipment.estimated_delivery_at,
            shipment.promised_delivery_at,
        ),
        "updated_at": func.now(),
    }
    if event.event_type is Status.DELIVERED:
        changes["delivered_at"] = event.occurred_at
    session.execute(update(Shipment).where(Shipment.id == shipment.id).values(**changes))
    session.execute(update(TrackingEvent).where(TrackingEvent.id == event_id).values(applied=True))
    session.commit()
    return ApplyResult.APPLIED
