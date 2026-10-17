"""SHIPTRACK_CLOUD picks the implementation of each port, and checks only that cloud's settings."""

from typing import Any

import google.cloud.pubsub_v1
import google.cloud.storage
import pytest

from shiptrack import cloud
from shiptrack.config import ConfigError, Settings
from shiptrack.events.publisher import SqsEventPublisher
from shiptrack.events.sqs import EventBridgeNotifier, SqsQueue
from shiptrack.gcp import pubsub
from shiptrack.gcp.pubsub import PubSubEventPublisher, PubSubNotifier, PubSubQueue
from shiptrack.gcp.secrets import SecretManagerSource
from shiptrack.gcp.storage import ProofOfDeliveryBucket
from shiptrack.secrets import AwsSecretSource
from shiptrack.storage.s3 import ProofOfDeliveryStore


def make(**env: Any) -> Settings:
    return Settings(_env_file=None, **env)  # type: ignore[arg-type]


GCP = {
    "cloud": "gcp",
    "gcp_project": "p",
    "db_secret_name": "db-app",
    "db_migrator_secret_name": "db-migrator",
    "events_topic": "events",
    "events_subscription": "events-worker",
    "notify_topic": "notify",
    "notify_subscription": "notify-worker",
    "proof_of_delivery_bucket": "pod-bucket",
    "proof_of_delivery_signer": "signer@example.invalid",
}


@pytest.fixture()
def no_google_clients(monkeypatch: pytest.MonkeyPatch) -> None:
    """The factories build clients; keep them from reaching for credentials."""

    class Client:
        def __init__(self, *_: Any, **__: Any) -> None: ...

        def topic_path(self, project: str, topic: str) -> str:
            return f"projects/{project}/topics/{topic}"

        def subscription_path(self, project: str, name: str) -> str:
            return f"projects/{project}/subscriptions/{name}"

    monkeypatch.setattr(pubsub, "_publisher_client", Client)
    monkeypatch.setattr(google.cloud.pubsub_v1, "SubscriberClient", Client)
    monkeypatch.setattr(google.cloud.storage, "Client", Client)


def test_aws_is_the_default() -> None:
    assert make().cloud == "aws"


def test_an_unknown_cloud_is_refused() -> None:
    with pytest.raises(ValueError, match="cloud"):
        make(cloud="mars")


def test_the_aws_ports_are_the_aws_classes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    settings = make(
        events_queue_url="http://q",
        notify_queue_url="http://n",
        event_bus_name="bus",
        pod_bucket="b",
    )
    assert isinstance(cloud.build_secret_source(settings), AwsSecretSource)
    assert isinstance(cloud.build_event_publisher(settings), SqsEventPublisher)
    assert isinstance(cloud.build_events_queue(settings), SqsQueue)
    assert isinstance(cloud.build_notify_queue(settings), SqsQueue)
    assert isinstance(cloud.build_notifier(settings), EventBridgeNotifier)
    assert isinstance(cloud.build_object_store(settings), ProofOfDeliveryStore)


def test_the_gcp_ports_are_the_gcp_classes(no_google_clients: None) -> None:
    settings = make(**GCP)
    assert isinstance(cloud.build_secret_source(settings), SecretManagerSource)
    assert isinstance(cloud.build_event_publisher(settings), PubSubEventPublisher)
    assert isinstance(cloud.build_events_queue(settings), PubSubQueue)
    assert isinstance(cloud.build_notify_queue(settings), PubSubQueue)
    assert isinstance(cloud.build_notifier(settings), PubSubNotifier)
    assert isinstance(cloud.build_object_store(settings), ProofOfDeliveryBucket)


def test_no_notification_target_means_no_notifier() -> None:
    assert cloud.build_notifier(make()) is None
    assert cloud.build_notifier(make(**{**GCP, "notify_topic": None})) is None


@pytest.mark.parametrize(
    ("call", "missing"),
    [
        (cloud.build_secret_source, "GCP_PROJECT"),
        (cloud.build_event_publisher, "GCP_PROJECT"),
        (cloud.build_events_queue, "GCP_PROJECT"),
        (cloud.build_object_store, "GCP_PROJECT"),
    ],
)
def test_an_unset_gcp_variable_is_an_error_on_gcp(call: Any, missing: str) -> None:
    settings = make(**{**GCP, "gcp_project": None})
    with pytest.raises(ConfigError, match=missing):
        call(settings)


@pytest.mark.parametrize(
    ("method", "field", "variable"),
    [
        ("require_db_secret", "db_secret_name", "DB_SECRET_NAME"),
        ("require_migrator_secret", "db_migrator_secret_name", "DB_MIGRATOR_SECRET_NAME"),
        ("require_events_destination", "events_topic", "EVENTS_TOPIC"),
        ("require_events_source", "events_subscription", "EVENTS_SUBSCRIPTION"),
        ("require_notify_source", "notify_subscription", "NOTIFY_SUBSCRIPTION"),
        ("require_pod_bucket", "proof_of_delivery_bucket", "PROOF_OF_DELIVERY_BUCKET"),
        (
            "require_proof_of_delivery_signer",
            "proof_of_delivery_signer",
            "PROOF_OF_DELIVERY_SIGNER",
        ),
    ],
)
def test_each_gcp_setting_is_required_on_gcp(method: str, field: str, variable: str) -> None:
    assert getattr(make(**GCP), method)()
    with pytest.raises(ConfigError, match=f"SHIPTRACK_{variable} is required"):
        getattr(make(**{**GCP, field: None}), method)()


def test_gcp_variables_are_not_needed_on_aws_and_aws_variables_are_not_needed_on_gcp() -> None:
    with pytest.raises(ConfigError, match="SHIPTRACK_EVENTS_QUEUE_URL"):
        make().require_events_destination()
    with pytest.raises(ConfigError, match="SHIPTRACK_EVENTS_TOPIC"):
        make(cloud="gcp", events_queue_url="http://q").require_events_destination()
