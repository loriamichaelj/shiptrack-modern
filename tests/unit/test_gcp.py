"""The GCP implementations of the ports, against fakes of each Google client."""

import json
import uuid
from concurrent.futures import Future
from datetime import UTC, datetime
from io import BytesIO
from types import SimpleNamespace
from typing import Any

import pytest
from google.api_core import exceptions as api_exceptions

from shiptrack.domain.status import Status
from shiptrack.events.messages import EventMessage
from shiptrack.gcp.pubsub import PubSubEventPublisher, PubSubNotifier, PubSubQueue
from shiptrack.gcp.secrets import SecretManagerSource
from shiptrack.gcp.storage import ProofOfDeliveryBucket, object_key
from shiptrack.ports import (
    NotificationFailedError,
    PayloadTooLargeError,
    QueueUnavailableError,
    ReceivedMessage,
)

TOPIC = "projects/p/topics/t"
SUBSCRIPTION = "projects/p/subscriptions/s"


# -- Secret Manager ------------------------------------------------------------------------------


def test_a_secret_is_read_at_its_latest_version_in_the_project() -> None:
    requests: list[dict[str, str]] = []

    class Client:
        def access_secret_version(self, request: dict[str, str]) -> Any:
            requests.append(request)
            return SimpleNamespace(payload=SimpleNamespace(data=b'{"a": 1}'))

    assert SecretManagerSource("proj", Client()).fetch("db-app") == '{"a": 1}'
    assert requests == [{"name": "projects/proj/secrets/db-app/versions/latest"}]


# -- Pub/Sub -------------------------------------------------------------------------------------


def event() -> EventMessage:
    return EventMessage(
        shipment_id=uuid.uuid4(),
        idempotency_key="key-1",
        event_type=Status.IN_TRANSIT,
        location="X",
        occurred_at=datetime(2026, 10, 1, tzinfo=UTC),
        payload=None,
        received_at=datetime(2026, 10, 1, tzinfo=UTC),
        request_id="r1",
    )


class FakePublisher:
    def __init__(self, outcome: Exception | None = None) -> None:
        self.outcome = outcome
        self.published: list[tuple[str, bytes, dict[str, str]]] = []

    def topic_path(self, project: str, topic: str) -> str:
        return f"projects/{project}/topics/{topic}"

    def publish(self, topic: str, data: bytes, **attributes: str) -> Future[str]:
        self.published.append((topic, data, attributes))
        future: Future[str] = Future()
        if self.outcome:
            future.set_exception(self.outcome)
        else:
            future.set_result("id")
        return future


def test_the_publisher_waits_for_the_result_and_sets_the_idempotency_key() -> None:
    client = FakePublisher()
    PubSubEventPublisher("p", "t", client).publish(event())
    topic, data, attributes = client.published[0]
    assert topic == TOPIC
    assert attributes == {"idempotency_key": "key-1"}
    assert EventMessage.from_json(data.decode()).idempotency_key == "key-1"


@pytest.mark.parametrize(
    "failure", [api_exceptions.ServiceUnavailable("down"), api_exceptions.PermissionDenied("no")]
)
def test_a_failed_publish_is_queue_unavailable(failure: Exception) -> None:
    with pytest.raises(QueueUnavailableError):
        PubSubEventPublisher("p", "t", FakePublisher(failure)).publish(event())


def test_the_notifier_sends_the_aws_envelope_and_the_filter_attribute() -> None:
    client = FakePublisher()
    PubSubNotifier("p", "t", client).send("ShipmentDelivered", {"event_id": "e1"})
    _, data, attributes = client.published[0]
    assert attributes == {"detail_type": "ShipmentDelivered"}
    assert json.loads(data) == {
        "source": "shiptrack.events",
        "detail-type": "ShipmentDelivered",
        "detail": {"event_id": "e1"},
    }


def test_a_failed_notification_is_reported() -> None:
    notifier = PubSubNotifier("p", "t", FakePublisher(api_exceptions.DeadlineExceeded("slow")))
    with pytest.raises(NotificationFailedError):
        notifier.send("ShipmentDelivered", {})


class FakeSubscriber:
    def __init__(self, *bodies: str, error: Exception | None = None) -> None:
        self.pending = [
            SimpleNamespace(ack_id=f"a{i}", message=SimpleNamespace(data=body.encode()))
            for i, body in enumerate(bodies)
        ]
        self.error = error
        self.pulls: list[dict[str, Any]] = []
        self.acked: list[str] = []
        self.released: list[tuple[str, int]] = []

    def subscription_path(self, project: str, name: str) -> str:
        return f"projects/{project}/subscriptions/{name}"

    def pull(self, request: dict[str, Any], timeout: float) -> Any:
        self.pulls.append(request)
        if self.error:
            raise self.error
        batch, self.pending = self.pending[: request["max_messages"]], self.pending[10:]
        return SimpleNamespace(received_messages=batch)

    def acknowledge(self, request: dict[str, Any]) -> None:
        self.acked.extend(request["ack_ids"])

    def modify_ack_deadline(self, request: dict[str, Any]) -> None:
        self.released.extend((i, request["ack_deadline_seconds"]) for i in request["ack_ids"])


def test_receive_pulls_a_batch_and_returns_bodies_with_their_ack_ids() -> None:
    client = FakeSubscriber("one", "two")
    queue = PubSubQueue("p", "s", client)
    messages = queue.receive(10, 20)
    assert [(m.body, m.handle) for m in messages] == [("one", "a0"), ("two", "a1")]
    assert client.pulls == [{"subscription": SUBSCRIPTION, "max_messages": 10}]


def test_an_empty_pull_that_times_out_is_not_an_error() -> None:
    queue = PubSubQueue("p", "s", FakeSubscriber(error=api_exceptions.DeadlineExceeded("idle")))
    assert queue.receive(10, 20) == []


def test_other_api_errors_reach_the_worker_as_transient_errors() -> None:
    queue = PubSubQueue("p", "s", FakeSubscriber(error=api_exceptions.ServiceUnavailable("down")))
    with pytest.raises(queue.transient_errors):
        queue.receive(10, 20)


def test_acknowledge_settles_and_release_redelivers_at_once() -> None:
    client = FakeSubscriber()
    queue = PubSubQueue("p", "s", client)
    queue.acknowledge(ReceivedMessage("x", "a1"))
    queue.release(ReceivedMessage("y", "a2"))
    assert client.acked == ["a1"]
    assert client.released == [("a2", 0)]


# -- Cloud Storage -------------------------------------------------------------------------------

SHIPMENT = uuid.UUID(int=1)
DOCUMENT = uuid.UUID(int=2)


class FakeBlob:
    def __init__(self, store: FakeStorage, key: str) -> None:
        self.store, self.key = store, key

    def upload_from_file(self, stream: Any, content_type: str) -> None:
        data = b""
        while chunk := stream.read(8):
            data += chunk
        assert stream.tell() == len(data)  # the resumable upload asks for the position
        self.store.objects[self.key] = (data, content_type)

    def delete(self) -> None:
        self.store.objects.pop(self.key)

    def generate_signed_url(self, **kwargs: Any) -> str:
        self.store.signed.append({"key": self.key, **kwargs})
        return "https://signed.invalid/object"


class FakeStorage:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.signed: list[dict[str, Any]] = []

    def bucket(self, name: str) -> Any:
        return SimpleNamespace(blob=lambda key: FakeBlob(self, key))


def bucket(client: FakeStorage) -> ProofOfDeliveryBucket:
    return ProofOfDeliveryBucket("p", "bkt", "signer@example.invalid", client, lambda: "token")


def test_the_object_key_spells_proof_of_delivery_out() -> None:
    assert object_key(SHIPMENT, DOCUMENT) == f"proof-of-delivery/{SHIPMENT}/{DOCUMENT}"


def test_save_streams_hashes_and_records_a_gs_uri() -> None:
    client = FakeStorage()
    stored = bucket(client).save(SHIPMENT, DOCUMENT, BytesIO(b"hello world"), "image/png", 100)
    assert client.objects[stored.key] == (b"hello world", "image/png")
    assert (stored.size_bytes, stored.uri) == (11, f"gs://bkt/{object_key(SHIPMENT, DOCUMENT)}")
    assert stored.sha256 == "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"


def test_save_refuses_a_file_over_the_limit_and_stores_nothing() -> None:
    client = FakeStorage()
    with pytest.raises(PayloadTooLargeError):
        bucket(client).save(SHIPMENT, DOCUMENT, BytesIO(b"x" * 101), "image/png", 100)
    assert client.objects == {}


def test_delete_removes_the_object() -> None:
    client = FakeStorage()
    store = bucket(client)
    stored = store.save(SHIPMENT, DOCUMENT, BytesIO(b"x"), "image/png", 100)
    store.delete(stored.key)
    assert client.objects == {}


@pytest.mark.parametrize(
    ("uri", "expected"),
    [
        ("gs://bkt/proof-of-delivery/a/b", ("bkt", "proof-of-delivery/a/b")),
        ("s3://bkt/pod/a/b", None),
        ("file:///var/lib/shiptrack/pod/a/b", None),
        ("gs:///no-bucket", None),
    ],
)
def test_locate_serves_only_gs_uris(uri: str, expected: tuple[str, str] | None) -> None:
    assert bucket(FakeStorage()).locate(uri) == expected


def test_the_signed_url_is_v4_short_lived_and_signed_through_the_iam_api() -> None:
    client = FakeStorage()
    url = bucket(client).presigned_url("bkt", "proof-of-delivery/a/b", "application/pdf")
    assert url == "https://signed.invalid/object"
    call = client.signed[0]
    assert call["version"] == "v4" and call["method"] == "GET"
    assert call["expiration"].total_seconds() == 300
    assert call["response_type"] == "application/pdf"
    assert call["service_account_email"] == "signer@example.invalid"
    assert call["access_token"] == "token"  # no key file: the IAM signing API does the signing
