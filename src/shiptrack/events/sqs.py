"""The AWS side of the queue ports: SQS to receive, EventBridge to announce (REM-06)."""

from __future__ import annotations

import json
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from shiptrack.ports import NotificationFailedError, ReceivedMessage

VISIBILITY_TIMEOUT_SECONDS = 60


class SqsQueue:
    """A long-polled SQS queue.

    A message that fails is left alone: it becomes visible again after the visibility timeout and
    reaches the dead-letter queue after the redrive policy's maxReceiveCount.
    """

    transient_errors: tuple[type[Exception], ...] = (ClientError, BotoCoreError)
    idle_backoff_seconds = 0.0  # the long poll is the wait

    def __init__(self, queue_url: str, region: str | None = None, client: Any = None) -> None:
        self._queue_url = queue_url
        self._client = client or boto3.client("sqs", region_name=region)

    def receive(self, max_messages: int, wait_seconds: int) -> list[ReceivedMessage]:
        response = self._client.receive_message(
            QueueUrl=self._queue_url,
            MaxNumberOfMessages=max_messages,
            WaitTimeSeconds=wait_seconds,
            VisibilityTimeout=VISIBILITY_TIMEOUT_SECONDS,
            MessageAttributeNames=["All"],
        )
        return [
            ReceivedMessage(body=message["Body"], handle=message["ReceiptHandle"])
            for message in response.get("Messages", [])
        ]

    def acknowledge(self, message: ReceivedMessage) -> None:
        self._client.delete_message(QueueUrl=self._queue_url, ReceiptHandle=message.handle)

    def release(self, message: ReceivedMessage) -> None:
        """Nothing to do: the visibility timeout makes the message available again."""


class EventBridgeNotifier:
    """Announce a change on the event bus; a rule routes it to the notifications queue."""

    def __init__(self, bus_name: str, region: str | None = None, client: Any = None) -> None:
        self._bus_name = bus_name
        self._client = client or boto3.client("events", region_name=region)

    def send(self, detail_type: str, detail: dict[str, Any]) -> None:
        entry = {
            "Source": "shiptrack.events",
            "DetailType": detail_type,
            "Detail": json.dumps(detail),
            "EventBusName": self._bus_name,
        }
        try:
            response = self._client.put_events(Entries=[entry])
        except (ClientError, BotoCoreError) as exc:
            raise NotificationFailedError(type(exc).__name__) from exc
        if response.get("FailedEntryCount", 0) != 0:
            raise NotificationFailedError("failed entry")
