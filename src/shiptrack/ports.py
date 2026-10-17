"""The cloud seam (ADR-0032): what the application needs from a cloud, and nothing else.

The same image runs on every cloud. `SHIPTRACK_CLOUD` picks an implementation of each port in
`shiptrack.cloud`; the rest of the code only sees these types. A port carries no SDK type, so the
workers, the routes, and the tests are the same on every cloud.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, BinaryIO, Protocol

if TYPE_CHECKING:
    from shiptrack.events.messages import EventMessage


class QueueUnavailableError(Exception):
    """The event could not be queued."""


class NotificationFailedError(Exception):
    """A notification could not be published."""


class PayloadTooLargeError(Exception):
    pass


@dataclass(frozen=True)
class StoredObject:
    bucket: str
    key: str
    size_bytes: int
    sha256: str
    scheme: str = "s3"

    @property
    def uri(self) -> str:
        return f"{self.scheme}://{self.bucket}/{self.key}"


@dataclass(frozen=True)
class ReceivedMessage:
    """One message off a queue. `handle` is whatever the queue needs to settle it."""

    body: str
    handle: Any


class SecretSource(Protocol):
    def fetch(self, name: str) -> str:
        """The secret's current value as text."""
        ...


class EventPublisher(Protocol):
    def publish(self, message: EventMessage) -> None:
        """Queue the event durably, or raise `QueueUnavailableError`."""
        ...


class MessageQueue(Protocol):
    # What `receive` raises when the queue service is unreachable: the worker logs and backs off.
    transient_errors: tuple[type[Exception], ...]
    # How long the worker waits after an empty receive, for a queue that does not long-poll.
    idle_backoff_seconds: float

    def receive(self, max_messages: int, wait_seconds: int) -> list[ReceivedMessage]: ...

    def acknowledge(self, message: ReceivedMessage) -> None:
        """The message was handled: it must not be delivered again."""
        ...

    def release(self, message: ReceivedMessage) -> None:
        """The message failed: let it be delivered again, and dead-lettered after enough tries."""
        ...


class Notifier(Protocol):
    def send(self, detail_type: str, detail: dict[str, Any]) -> None:
        """Announce a change, or raise `NotificationFailedError`."""
        ...


class ObjectStore(Protocol):
    def save(
        self,
        shipment_id: uuid.UUID,
        document_id: uuid.UUID,
        stream: BinaryIO,
        content_type: str,
        max_bytes: int,
    ) -> StoredObject:
        """Stream `stream` into the store while hashing it; refuse anything over `max_bytes`."""
        ...

    def delete(self, key: str) -> None: ...

    def locate(self, uri: str) -> tuple[str, str] | None:
        """(bucket, key) for a URI this store serves, or None for any other scheme."""
        ...

    def presigned_url(self, bucket: str, key: str, content_type: str) -> str:
        """A short-lived URL the caller is redirected to; the bytes never pass through the API."""
        ...
