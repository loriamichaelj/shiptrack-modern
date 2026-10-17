"""Pub/Sub for the events queue and the notifications (REM-06 on GCP).

The events subscription is a pull subscription with a 60 second acknowledge deadline and a
dead-letter topic after five delivery attempts. Delivery is at least once; the worker is already
idempotent on `idempotency_key`. The notification topic has a subscription filtered on the
`detail_type` attribute, which the notifier sets.
"""

from __future__ import annotations

import json
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Any

import google.cloud.pubsub_v1
import structlog
from google.api_core import exceptions as api_exceptions
from google.auth import exceptions as auth_exceptions

from shiptrack import metrics
from shiptrack.events.messages import EventMessage
from shiptrack.ports import NotificationFailedError, QueueUnavailableError, ReceivedMessage

log = structlog.get_logger("shiptrack.events")

PUBLISH_TIMEOUT_SECONDS = 10.0
# After an empty pull, wait this long before asking again, so an idle worker is not a busy loop.
IDLE_BACKOFF_SECONDS = 1.0

PUBLISH_ERRORS = (
    api_exceptions.GoogleAPICallError,
    api_exceptions.RetryError,
    auth_exceptions.GoogleAuthError,
    FutureTimeout,
)


def _publisher_client() -> Any:
    return google.cloud.pubsub_v1.PublisherClient()


class PubSubEventPublisher:
    """Publish and wait for the result, so a 202 still means the event is durably queued."""

    def __init__(self, project: str, topic: str, client: Any = None) -> None:
        self._client = client or _publisher_client()
        self._topic_path = self._client.topic_path(project, topic)

    def publish(self, message: EventMessage) -> None:
        try:
            future = self._client.publish(
                self._topic_path,
                message.to_json().encode("utf-8"),
                idempotency_key=message.idempotency_key,
            )
            future.result(timeout=PUBLISH_TIMEOUT_SECONDS)
        except PUBLISH_ERRORS as exc:
            metrics.EVENTS_ENQUEUED.labels(result="failed").inc()
            log.error("event_enqueue_failed", error=type(exc).__name__)
            raise QueueUnavailableError from exc
        metrics.EVENTS_ENQUEUED.labels(result="ok").inc()


class PubSubNotifier:
    """Announce a change on the notification topic.

    The body has the same shape as the AWS envelope (`detail-type` and `detail`), so the notify
    worker reads both clouds alike. The `detail_type` attribute is what the subscription filters on.
    """

    def __init__(self, project: str, topic: str, client: Any = None) -> None:
        self._client = client or _publisher_client()
        self._topic_path = self._client.topic_path(project, topic)

    def send(self, detail_type: str, detail: dict[str, Any]) -> None:
        envelope = {"source": "shiptrack.events", "detail-type": detail_type, "detail": detail}
        try:
            future = self._client.publish(
                self._topic_path,
                json.dumps(envelope).encode("utf-8"),
                detail_type=detail_type,
            )
            future.result(timeout=PUBLISH_TIMEOUT_SECONDS)
        except PUBLISH_ERRORS as exc:
            raise NotificationFailedError(type(exc).__name__) from exc


class PubSubQueue:
    """A pull subscription. The acknowledge deadline is a property of the subscription (60 s)."""

    transient_errors: tuple[type[Exception], ...] = (
        api_exceptions.GoogleAPICallError,
        api_exceptions.RetryError,
        auth_exceptions.GoogleAuthError,
    )
    idle_backoff_seconds = IDLE_BACKOFF_SECONDS

    def __init__(self, project: str, subscription: str, client: Any = None) -> None:
        self._client = client or google.cloud.pubsub_v1.SubscriberClient()
        self._subscription_path = self._client.subscription_path(project, subscription)

    def receive(self, max_messages: int, wait_seconds: int) -> list[ReceivedMessage]:
        try:
            response = self._client.pull(
                request={"subscription": self._subscription_path, "max_messages": max_messages},
                # The server holds an empty pull for about 29 seconds. Bound it to the poll's wait,
                # as SQS's long poll is, so SIGTERM never waits longer than that for the loop.
                timeout=max(float(wait_seconds), 1.0),
            )
        except api_exceptions.DeadlineExceeded:
            return []  # the server had nothing to send within the wait
        return [
            ReceivedMessage(body=item.message.data.decode("utf-8"), handle=item.ack_id)
            for item in response.received_messages
        ]

    def acknowledge(self, message: ReceivedMessage) -> None:
        self._client.acknowledge(
            request={"subscription": self._subscription_path, "ack_ids": [message.handle]}
        )

    def release(self, message: ReceivedMessage) -> None:
        """A zero acknowledge deadline is a negative acknowledgement: redeliver at once."""
        self._client.modify_ack_deadline(
            request={
                "subscription": self._subscription_path,
                "ack_ids": [message.handle],
                "ack_deadline_seconds": 0,
            }
        )
