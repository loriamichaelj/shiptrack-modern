"""Build the implementation of each port for the selected cloud (ADR-0032).

This is the only module that knows which cloud classes exist. A cloud's SDK is imported when its
branch runs, so a process on one cloud never loads the others' clients.
"""

from __future__ import annotations

from shiptrack.config import Settings
from shiptrack.events.publisher import SqsEventPublisher
from shiptrack.events.sqs import EventBridgeNotifier, SqsQueue
from shiptrack.ports import EventPublisher, MessageQueue, Notifier, ObjectStore, SecretSource
from shiptrack.secrets import AwsSecretSource, SecretCache
from shiptrack.storage.s3 import ProofOfDeliveryStore


def build_secret_source(settings: Settings) -> SecretSource:
    if settings.cloud == "gcp":
        from shiptrack.gcp.secrets import SecretManagerSource

        return SecretManagerSource(settings.require_gcp_project())
    return AwsSecretSource(settings.aws_region)


def build_secret_cache(settings: Settings) -> SecretCache:
    return SecretCache(source=build_secret_source(settings))


def build_event_publisher(settings: Settings) -> EventPublisher:
    """The API's side of the events queue."""
    if settings.cloud == "gcp":
        from shiptrack.gcp.pubsub import PubSubEventPublisher

        return PubSubEventPublisher(
            settings.require_gcp_project(), settings.require_events_destination()
        )
    return SqsEventPublisher(settings.require_events_destination(), settings.aws_region)


def build_events_queue(settings: Settings) -> MessageQueue:
    """worker-events reads the events queue."""
    if settings.cloud == "gcp":
        from shiptrack.gcp.pubsub import PubSubQueue

        return PubSubQueue(settings.require_gcp_project(), settings.require_events_source())
    return SqsQueue(settings.require_events_source(), settings.aws_region)


def build_notify_queue(settings: Settings) -> MessageQueue:
    """worker-notify reads the notifications queue."""
    if settings.cloud == "gcp":
        from shiptrack.gcp.pubsub import PubSubQueue

        return PubSubQueue(settings.require_gcp_project(), settings.require_notify_source())
    return SqsQueue(settings.require_notify_source(), settings.aws_region)


def build_notifier(settings: Settings) -> Notifier | None:
    """How worker-events announces a delivery or an exception; None when no target is set."""
    if settings.cloud == "gcp":
        if not settings.notify_topic:
            return None
        from shiptrack.gcp.pubsub import PubSubNotifier

        return PubSubNotifier(settings.require_gcp_project(), settings.notify_topic)
    if not settings.event_bus_name:
        return None
    return EventBridgeNotifier(settings.event_bus_name, settings.aws_region)


def build_object_store(settings: Settings) -> ObjectStore:
    if settings.cloud == "gcp":
        from shiptrack.gcp.storage import ProofOfDeliveryBucket

        return ProofOfDeliveryBucket(
            settings.require_gcp_project(),
            settings.require_pod_bucket(),
            settings.require_proof_of_delivery_signer(),
        )
    return ProofOfDeliveryStore(settings.require_pod_bucket(), settings.aws_region)
