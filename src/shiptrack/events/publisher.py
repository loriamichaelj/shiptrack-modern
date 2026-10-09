"""Send events to the queue before acknowledging them (REM-06).

The API answers 202 only after SendMessage has succeeded. If it fails, the caller gets a 503 and
knows to retry; an event that was not durably queued is never acknowledged.
"""

from __future__ import annotations

from typing import Any

import boto3
import structlog
from botocore.exceptions import BotoCoreError, ClientError

from shiptrack import metrics
from shiptrack.events.messages import EventMessage

log = structlog.get_logger("shiptrack.events")


class QueueUnavailableError(Exception):
    """The event could not be queued."""


class EventPublisher:
    def __init__(self, queue_url: str, region: str | None = None, client: Any = None) -> None:
        self._queue_url = queue_url
        self._client = client or boto3.client("sqs", region_name=region)

    def publish(self, message: EventMessage) -> None:
        try:
            self._client.send_message(
                QueueUrl=self._queue_url,
                MessageBody=message.to_json(),
                MessageAttributes={
                    "idempotency_key": {
                        "DataType": "String",
                        "StringValue": message.idempotency_key,
                    }
                },
            )
        except (ClientError, BotoCoreError) as exc:
            metrics.EVENTS_ENQUEUED.labels(result="failed").inc()
            log.error("event_enqueue_failed", error=type(exc).__name__)
            raise QueueUnavailableError from exc
        metrics.EVENTS_ENQUEUED.labels(result="ok").inc()
