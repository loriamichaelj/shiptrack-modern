"""The GCP ports against the Pub/Sub emulator and a fake Cloud Storage server (G1).

Start them as compose.yaml and the CI workflow do, and point the Google clients at them:

    PUBSUB_EMULATOR_HOST=127.0.0.1:8085  STORAGE_EMULATOR_HOST=http://127.0.0.1:4443

Secret Manager has no emulator, so the secret source is a fake. The IAM signing call behind a
signed URL cannot be emulated either; the unit tests check what it is asked, and the first
deployment checks the signature.
"""

import io
import json
import os
import time
import uuid
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import google.cloud.pubsub_v1
import google.cloud.storage
import pytest
from fastapi.testclient import TestClient
from google.auth.credentials import AnonymousCredentials
from sqlalchemy import Engine, text
from sqlalchemy.engine import URL

from shiptrack import cloud
from shiptrack.cloud import build_events_queue, build_notifier, build_notify_queue
from shiptrack.config import Settings
from shiptrack.events.worker import EventWorker, NotifyWorker
from shiptrack.gcp.storage import ProofOfDeliveryBucket
from shiptrack.main import create_app
from shiptrack.ports import PayloadTooLargeError

from .conftest import NOW, iso

PROJECT = "proj"
EMULATORS = bool(os.environ.get("PUBSUB_EMULATOR_HOST") and os.environ.get("STORAGE_EMULATOR_HOST"))

# In CI the emulators must be there, so a missing one fails instead of skipping.
pytestmark = pytest.mark.skipif(
    not EMULATORS and not os.environ.get("CI"), reason="the GCP emulators are not running"
)


class Names:
    def __init__(self) -> None:
        suffix = uuid.uuid4().hex[:8]
        self.events_topic = f"events-{suffix}"
        self.events_dead_topic = f"events-dead-{suffix}"
        self.events_dead_subscription = f"events-dead-inspect-{suffix}"
        self.events_subscription = f"events-worker-{suffix}"
        self.notify_topic = f"notify-{suffix}"
        self.notify_subscription = f"notify-worker-{suffix}"
        self.bucket = f"proof-of-delivery-{suffix}"


@pytest.fixture()
def names() -> Iterator[Names]:
    n = Names()
    publisher = google.cloud.pubsub_v1.PublisherClient()
    subscriber = google.cloud.pubsub_v1.SubscriberClient()
    topic = publisher.topic_path
    sub = subscriber.subscription_path
    for name in (n.events_topic, n.events_dead_topic, n.notify_topic):
        publisher.create_topic(request={"name": topic(PROJECT, name)})
    subscriber.create_subscription(
        request={
            "name": sub(PROJECT, n.events_dead_subscription),
            "topic": topic(PROJECT, n.events_dead_topic),
        }
    )
    subscriber.create_subscription(
        request={
            "name": sub(PROJECT, n.events_subscription),
            "topic": topic(PROJECT, n.events_topic),
            "ack_deadline_seconds": 60,
            "dead_letter_policy": {
                "dead_letter_topic": topic(PROJECT, n.events_dead_topic),
                "max_delivery_attempts": 5,
            },
        }
    )
    subscriber.create_subscription(
        request={
            "name": sub(PROJECT, n.notify_subscription),
            "topic": topic(PROJECT, n.notify_topic),
            "filter": 'hasPrefix(attributes.detail_type, "Shipment")',
        }
    )
    storage = google.cloud.storage.Client(project=PROJECT, credentials=AnonymousCredentials())
    storage.create_bucket(n.bucket)
    yield n


class FakeSecretSource:
    def __init__(self, url: URL) -> None:
        self._secret = json.dumps(
            {
                "username": url.username,
                "password": url.password,
                "host": url.host,
                "port": url.port or 5432,
                "dbname": url.database,
            }
        )

    def fetch(self, name: str) -> str:
        return self._secret


@pytest.fixture()
def gcp_settings(database_url: URL, names: Names, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setattr(cloud, "build_secret_source", lambda _: FakeSecretSource(database_url))
    return Settings(
        cloud="gcp",
        gcp_project=PROJECT,
        db_secret_name="db-app",
        db_sslmode="disable",
        events_topic=names.events_topic,
        events_subscription=names.events_subscription,
        notify_topic=names.notify_topic,
        notify_subscription=names.notify_subscription,
        proof_of_delivery_bucket=names.bucket,
        proof_of_delivery_signer="signer@example.invalid",
    )


@pytest.fixture()
def gcp_client(gcp_settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(gcp_settings)) as client:
        yield client


def new_shipment(client: TestClient) -> str:
    response = client.post(
        "/api/v1/shipments",
        json={
            "carrier_code": "ACME",
            "origin": "Rotterdam",
            "destination": "Chicago",
            "promised_delivery_at": iso(NOW + timedelta(days=5)),
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def post_event(client: TestClient, shipment_id: str, key: str, event_type: str) -> None:
    response = client.post(
        f"/api/v1/shipments/{shipment_id}/events",
        headers={"Idempotency-Key": key},
        json={"event_type": event_type, "location": "Hub", "occurred_at": iso(NOW)},
    )
    assert response.status_code == 202, response.text


def poll_until(worker: Any, count: int, tries: int = 15) -> int:
    """Pull until `count` messages were handled; Pub/Sub delivery is not instant."""
    handled = 0
    for _ in range(tries):
        handled += worker.poll_once(2)
        if handled >= count:
            return handled
        time.sleep(0.2)
    return handled


def test_an_event_goes_from_the_api_through_pubsub_to_the_database_and_a_notification(
    gcp_client: TestClient, gcp_settings: Settings, engine: Engine
) -> None:
    shipment_id = new_shipment(gcp_client)
    post_event(gcp_client, shipment_id, "d-1", "DELIVERED")
    with engine.connect() as connection:  # accepted, not yet applied
        assert connection.scalar(text("SELECT count(*) FROM shiptrack.tracking_events")) == 0

    events = EventWorker(
        build_events_queue(gcp_settings),
        gcp_client.app.state.session_factory,  # type: ignore[attr-defined]
        notifier=build_notifier(gcp_settings),
        sleep=lambda _: None,
    )
    assert poll_until(events, 1) == 1
    with engine.connect() as connection:
        status = connection.scalar(text("SELECT status FROM shiptrack.shipments"))
    assert status == "DELIVERED"

    notify = NotifyWorker(build_notify_queue(gcp_settings))
    assert poll_until(notify, 1) == 1  # the envelope and the filter work as the AWS ones do


def test_a_message_that_always_fails_is_dead_lettered_after_five_attempts(
    gcp_settings: Settings, names: Names
) -> None:
    publisher = google.cloud.pubsub_v1.PublisherClient()
    publisher.publish(
        publisher.topic_path(PROJECT, names.events_topic), b"not json", idempotency_key="bad"
    ).result(timeout=10)
    worker = EventWorker(
        build_events_queue(gcp_settings),
        lambda: None,
        sleep=lambda _: None,  # type: ignore[arg-type]
    )
    attempts = 0
    for _ in range(40):
        attempts += worker.poll_once(1)
        dead = google.cloud.pubsub_v1.SubscriberClient().pull(
            request={
                "subscription": google.cloud.pubsub_v1.SubscriberClient().subscription_path(
                    PROJECT, names.events_dead_subscription
                ),
                "max_messages": 1,
            },
            timeout=2,
        )
        if dead.received_messages:
            break
    assert attempts == 5
    assert dead.received_messages[0].message.data == b"not json"


def test_the_subscription_filter_drops_what_is_not_a_shipment_notification(
    gcp_settings: Settings, names: Names
) -> None:
    publisher = google.cloud.pubsub_v1.PublisherClient()
    topic = publisher.topic_path(PROJECT, names.notify_topic)
    publisher.publish(topic, b"{}", detail_type="Unrelated").result(timeout=10)
    assert build_notify_queue(gcp_settings).receive(10, 1) == []


# -- Cloud Storage -------------------------------------------------------------------------------

SHIPMENT = uuid.uuid4()
PNG = b"\x89PNG\r\n\x1a\n" + b"proof" * 100


def bucket_store(settings: Settings) -> ProofOfDeliveryBucket:
    return ProofOfDeliveryBucket(
        PROJECT,
        settings.require_pod_bucket(),
        "signer@example.invalid",
        client=google.cloud.storage.Client(project=PROJECT, credentials=AnonymousCredentials()),
    )


def read_back(settings: Settings, key: str) -> bytes:
    client = google.cloud.storage.Client(project=PROJECT, credentials=AnonymousCredentials())
    return bytes(client.bucket(settings.require_pod_bucket()).blob(key).download_as_bytes())


def test_save_streams_through_a_real_resumable_upload(gcp_settings: Settings) -> None:
    document = uuid.uuid4()
    stored = bucket_store(gcp_settings).save(
        SHIPMENT, document, io.BytesIO(PNG), "image/png", 10**6
    )
    assert stored.size_bytes == len(PNG)
    assert stored.uri == f"gs://{gcp_settings.proof_of_delivery_bucket}/{stored.key}"
    assert read_back(gcp_settings, stored.key) == PNG


def test_a_file_over_the_limit_stops_the_upload_and_leaves_no_object(
    gcp_settings: Settings,
) -> None:
    store = bucket_store(gcp_settings)
    document = uuid.uuid4()
    with pytest.raises(PayloadTooLargeError):
        store.save(
            SHIPMENT, document, io.BytesIO(b"x" * (3 * 1024 * 1024)), "image/png", 1024 * 1024
        )
    client = google.cloud.storage.Client(project=PROJECT, credentials=AnonymousCredentials())
    assert list(client.list_blobs(gcp_settings.proof_of_delivery_bucket)) == []


def test_delete_removes_the_object(gcp_settings: Settings) -> None:
    store = bucket_store(gcp_settings)
    stored = store.save(SHIPMENT, uuid.uuid4(), io.BytesIO(PNG), "image/png", 10**6)
    store.delete(stored.key)
    client = google.cloud.storage.Client(project=PROJECT, credentials=AnonymousCredentials())
    assert list(client.list_blobs(gcp_settings.proof_of_delivery_bucket)) == []


def test_the_api_stores_a_gs_uri_and_redirects_the_download(
    gcp_client: TestClient,
    gcp_settings: Settings,
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signed: list[tuple[str, str, str]] = []

    def fake_signed_url(self: Any, bucket: str, key: str, content_type: str) -> str:
        signed.append((bucket, key, content_type))
        return "https://signed.invalid/object"

    monkeypatch.setattr(ProofOfDeliveryBucket, "presigned_url", fake_signed_url)
    shipment_id = new_shipment(gcp_client)
    response = gcp_client.post(
        f"/api/v1/shipments/{shipment_id}/pod", files={"file": ("p.png", PNG, "image/png")}
    )
    assert response.status_code == 201, response.text
    document_id = response.json()["document_id"]
    with engine.connect() as connection:
        uri = connection.scalar(text("SELECT storage_uri FROM shiptrack.pod_documents"))
    assert uri.startswith(f"gs://{gcp_settings.proof_of_delivery_bucket}/proof-of-delivery/")

    download = gcp_client.get(
        f"/api/v1/shipments/{shipment_id}/pod/{document_id}", follow_redirects=False
    )
    assert download.status_code == 302
    assert download.headers["location"] == "https://signed.invalid/object"
    assert signed[0][2] == "image/png"
    assert read_back(gcp_settings, signed[0][1]) == PNG


def test_an_s3_uri_is_not_served_on_gcp(gcp_client: TestClient, engine: Engine) -> None:
    shipment_id = new_shipment(gcp_client)
    response = gcp_client.post(
        f"/api/v1/shipments/{shipment_id}/pod", files={"file": ("p.png", PNG, "image/png")}
    )
    document_id = response.json()["document_id"]
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE shiptrack.pod_documents SET storage_uri = 's3://b/pod/a/b'")
        )
    download = gcp_client.get(
        f"/api/v1/shipments/{shipment_id}/pod/{document_id}", follow_redirects=False
    )
    assert download.status_code == 500
