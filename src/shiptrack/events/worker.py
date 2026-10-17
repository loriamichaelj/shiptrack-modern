"""Queue consumers (REM-06): worker-events applies events, worker-notify logs notifications."""

from __future__ import annotations

import json
import threading
import time
from collections import OrderedDict
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from shiptrack import metrics
from shiptrack.db.models import Shipment
from shiptrack.domain.status import Status
from shiptrack.events.messages import EventMessage
from shiptrack.events.processor import ApplyResult, apply_event
from shiptrack.ports import MessageQueue, NotificationFailedError, Notifier

log = structlog.get_logger("shiptrack.worker")

LONG_POLL_SECONDS = 20
BATCH_SIZE = 10
HEARTBEAT_LIMIT_SECONDS = 120

# A change to one of these statuses is announced on the event bus.
NOTIFIED = {Status.DELIVERED: "ShipmentDelivered", Status.EXCEPTION: "ShipmentException"}
NOTIFY_ATTEMPTS = 3


class QueueWorker:
    """Poll a queue, handle each message on its own, and acknowledge only those that succeeded.

    A message that fails is released, so the queue delivers it again and, after its redelivery
    limit, moves it to the dead-letter queue.
    """

    def __init__(self, queue: MessageQueue) -> None:
        self._queue = queue
        self._stopping = threading.Event()
        self._last_beat = time.monotonic()

    # -- lifecycle ----------------------------------------------------------------------------

    def stop(self) -> None:
        """Stop polling. A message already being handled is finished first."""
        self._stopping.set()

    @property
    def stopping(self) -> bool:
        return self._stopping.is_set()

    def healthy(self) -> bool:
        """False when the poll loop has not made progress for two minutes."""
        return time.monotonic() - self._last_beat < HEARTBEAT_LIMIT_SECONDS

    def run(self) -> None:
        while not self.stopping:
            try:
                self.poll_once(LONG_POLL_SECONDS)
            except self._queue.transient_errors as exc:
                log.error("queue_poll_failed", error=type(exc).__name__)
                self._stopping.wait(5)  # back off, but wake at once on SIGTERM
        log.info("worker_stopped")

    # -- one poll -----------------------------------------------------------------------------

    def poll_once(self, wait_seconds: int = LONG_POLL_SECONDS) -> int:
        """Receive up to a batch, handle each message, and return how many were received."""
        self._last_beat = time.monotonic()
        messages = self._queue.receive(BATCH_SIZE, wait_seconds)
        for message in messages:
            if self.handle(message.body):
                self._queue.acknowledge(message)
            else:
                self._queue.release(message)
        if not messages and self._queue.idle_backoff_seconds:
            self._stopping.wait(self._queue.idle_backoff_seconds)
        self._last_beat = time.monotonic()
        return len(messages)

    def handle(self, body: str) -> bool:
        raise NotImplementedError


class EventWorker(QueueWorker):
    def __init__(
        self,
        queue: MessageQueue,
        session_factory: sessionmaker[Session],
        *,
        notifier: Notifier | None = None,
        sleep: Any = time.sleep,
    ) -> None:
        super().__init__(queue)
        self._session_factory = session_factory
        self._notifier = notifier
        self._sleep = sleep

    def handle(self, body: str) -> bool:
        try:
            event = EventMessage.from_json(body)
        except (KeyError, ValueError, json.JSONDecodeError) as exc:
            # A message that cannot be read will never succeed; the DLQ collects it.
            metrics.EVENTS_PROCESSED.labels(result="error").inc()
            log.error("event_message_unreadable", error=type(exc).__name__)
            return False

        try:
            with self._session_factory() as session:
                result = apply_event(session, event.to_queued_event())
        except Exception:
            metrics.EVENTS_PROCESSED.labels(result="error").inc()
            log.exception("event_apply_failed", idempotency_key=event.idempotency_key)
            return False

        metrics.EVENTS_PROCESSED.labels(result=result.value.lower()).inc()
        lag = (datetime.now(UTC) - event.received_at).total_seconds()
        metrics.EVENT_APPLY_LAG.observe(max(lag, 0.0))
        log.info(
            "event_handled",
            result=result.value.lower(),
            idempotency_key=event.idempotency_key,
            shipment_id=str(event.shipment_id),
            event_type=event.event_type.value,
            request_id=event.request_id,
        )
        if result is ApplyResult.APPLIED and event.event_type in NOTIFIED:
            self._announce(event)
        return True

    def _announce(self, event: EventMessage) -> None:
        """Announce the change, after the commit. A failure here loses the notification and not the
        data (the dual-write trade-off in the design)."""
        if self._notifier is None:
            return
        with self._session_factory() as session:
            tracking_number = session.scalar(
                select(Shipment.tracking_number).where(Shipment.id == event.shipment_id)
            )
        detail = {
            "event_id": event.idempotency_key,
            "shipment_id": str(event.shipment_id),
            "tracking_number": tracking_number,
            "status": event.event_type.value,
            "occurred_at": event.occurred_at.isoformat().replace("+00:00", "Z"),
        }
        for attempt in range(NOTIFY_ATTEMPTS):
            try:
                self._notifier.send(NOTIFIED[event.event_type], detail)
                return
            except NotificationFailedError as exc:
                log.warning("notification_send_failed", attempt=attempt + 1, error=str(exc))
            if attempt + 1 < NOTIFY_ATTEMPTS:
                self._sleep(0.2 * 2**attempt)
        log.error("notification_lost", idempotency_key=event.idempotency_key)


class NotifyWorker(QueueWorker):
    """Consumes the notifications queue (one envelope with `detail-type` and `detail` per message).

    It is idempotent on `detail.event_id` through a small in-memory cache. The window is bounded and
    documented: a repeat after a restart or past the cache is sent again.
    """

    CACHE_SIZE = 1000

    def __init__(self, queue: MessageQueue) -> None:
        super().__init__(queue)
        self._seen: OrderedDict[str, None] = OrderedDict()

    def _is_repeat(self, event_id: str) -> bool:
        if event_id in self._seen:
            self._seen.move_to_end(event_id)
            return True
        self._seen[event_id] = None
        if len(self._seen) > self.CACHE_SIZE:
            self._seen.popitem(last=False)
        return False

    def handle(self, body: str) -> bool:
        try:
            envelope = json.loads(body)
            detail = envelope["detail"]
            detail_type = envelope["detail-type"]
            event_id = detail["event_id"]
        except (KeyError, ValueError, TypeError) as exc:
            log.error("notification_unreadable", error=type(exc).__name__)
            return False
        if self._is_repeat(event_id):
            log.info("notification_repeat_ignored", event_id=event_id)
            return True
        log.info(
            "notification_sent",
            detail_type=detail_type,
            event_id=event_id,
            tracking_number=detail.get("tracking_number"),
            status=detail.get("status"),
        )
        metrics.NOTIFICATIONS_SENT.labels(detail_type=detail_type).inc()
        return True
