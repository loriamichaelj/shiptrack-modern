"""Tracking event ingestion (REM-06): validate, check the shipment, queue, then 202."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.orm import Session

from shiptrack.api.deps import get_shipment_or_404
from shiptrack.api.errors import ApiError
from shiptrack.db.session import get_session
from shiptrack.domain.models import EventAccepted, EventIn
from shiptrack.events.messages import EventMessage
from shiptrack.events.publisher import EventPublisher, QueueUnavailableError

router = APIRouter(prefix="/api/v1")

MAX_KEY_LENGTH = 64


@router.post("/shipments/{shipment_id}/events", status_code=202, response_model=EventAccepted)
def post_event(
    shipment_id: str,
    body: EventIn,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> EventAccepted:
    if idempotency_key is None or not idempotency_key.strip():
        raise ApiError(400, "MISSING_IDEMPOTENCY_KEY", "The Idempotency-Key header is required")
    if len(idempotency_key) > MAX_KEY_LENGTH:
        raise ApiError(
            422, "VALIDATION_ERROR", f"Idempotency-Key must be 1-{MAX_KEY_LENGTH} characters"
        )
    # The shipment is checked synchronously so an unknown shipment is a 404, not a lost event.
    shipment = get_shipment_or_404(session, shipment_id)

    publisher: EventPublisher = request.app.state.publisher
    message = EventMessage(
        shipment_id=shipment.id,
        idempotency_key=idempotency_key,
        event_type=body.event_type,
        location=body.location,
        occurred_at=body.occurred_at,
        payload=body.payload,
        received_at=datetime.now(UTC),
        request_id=getattr(request.state, "request_id", None),
    )
    try:
        publisher.publish(message)
    except QueueUnavailableError as exc:
        # Never acknowledge an event that was not durably queued.
        raise ApiError(503, "QUEUE_UNAVAILABLE", "The event could not be queued; retry") from exc
    return EventAccepted(accepted=True, idempotency_key=idempotency_key)
