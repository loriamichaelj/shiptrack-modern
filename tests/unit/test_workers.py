"""The SQS consumers against a fake client: what is deleted, what is left, and how they stop."""

import json
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import pytest

from shiptrack.domain.status import Status
from shiptrack.events import worker as worker_module
from shiptrack.events.messages import EventMessage
from shiptrack.events.processor import ApplyResult
from shiptrack.events.worker import EventWorker, NotifyWorker, QueueWorker


class FakeSqs:
    def __init__(self, *bodies: str) -> None:
        self.messages = [
            {"MessageId": str(i), "ReceiptHandle": f"h{i}", "Body": body}
            for i, body in enumerate(bodies)
        ]
        self.deleted: list[str] = []
        self.received_with: list[dict[str, Any]] = []

    def receive_message(self, **kwargs: Any) -> dict[str, Any]:
        self.received_with.append(kwargs)
        batch, self.messages = self.messages[:10], self.messages[10:]
        return {"Messages": batch} if batch else {}

    def delete_message(self, QueueUrl: str, ReceiptHandle: str) -> None:
        self.deleted.append(ReceiptHandle)


class FakeSession:
    def scalar(self, *_: Any, **__: Any) -> str:
        return "MF0000000001"


@contextmanager
def fake_factory() -> Iterator[FakeSession]:
    yield FakeSession()


def body(key: str, event_type: Status = Status.IN_TRANSIT) -> str:
    return EventMessage(
        shipment_id=uuid.uuid4(),
        idempotency_key=key,
        event_type=event_type,
        location="X",
        occurred_at=datetime(2026, 10, 1, tzinfo=UTC),
        payload=None,
        received_at=datetime.now(UTC),
        request_id=None,
    ).to_json()


def make(sqs: FakeSqs, events: Any = None, bus: str | None = "bus") -> EventWorker:
    return EventWorker(
        "http://queue",
        fake_factory,  # type: ignore[arg-type]
        bus_name=bus,
        sqs=sqs,
        events=events,
        sleep=lambda _: None,
    )


def test_a_poll_asks_for_the_design_s_batch_and_timeouts() -> None:
    sqs = FakeSqs()
    make(sqs).poll_once()
    call = sqs.received_with[0]
    assert (call["MaxNumberOfMessages"], call["WaitTimeSeconds"], call["VisibilityTimeout"]) == (
        10,
        20,
        60,
    )


def test_only_messages_that_succeeded_are_deleted(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_apply(_: Any, event: Any) -> ApplyResult:
        if event.idempotency_key == "bad":
            raise RuntimeError("database down")
        return ApplyResult.APPLIED

    monkeypatch.setattr(worker_module, "apply_event", fake_apply)
    sqs = FakeSqs(body("a"), body("bad"), body("c"))
    assert make(sqs).poll_once(0) == 3
    assert sqs.deleted == ["h0", "h2"]  # "bad" stays for redelivery and, eventually, the DLQ


def test_an_unreadable_message_is_left_alone() -> None:
    sqs = FakeSqs("not json", json.dumps({"shipment_id": "x"}))
    make(sqs).poll_once(0)
    assert sqs.deleted == []


def test_a_duplicate_is_deleted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker_module, "apply_event", lambda *_: ApplyResult.DUPLICATE)
    sqs = FakeSqs(body("a"))
    make(sqs).poll_once(0)
    assert sqs.deleted == ["h0"]


class FakeEvents:
    def __init__(self, *failures: Exception | dict[str, int]) -> None:
        self.failures = list(failures)
        self.entries: list[dict[str, Any]] = []

    def put_events(self, Entries: list[dict[str, Any]]) -> dict[str, int]:
        self.entries.extend(Entries)
        if self.failures:
            outcome = self.failures.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        return {"FailedEntryCount": 0}


def test_delivered_and_exception_are_announced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker_module, "apply_event", lambda *_: ApplyResult.APPLIED)
    events = FakeEvents()
    sqs = FakeSqs(
        body("a", Status.DELIVERED), body("b", Status.EXCEPTION), body("c", Status.IN_TRANSIT)
    )
    make(sqs, events).poll_once(0)
    assert [e["DetailType"] for e in events.entries] == ["ShipmentDelivered", "ShipmentException"]
    detail = json.loads(events.entries[0]["Detail"])
    assert set(detail) == {"event_id", "shipment_id", "tracking_number", "status", "occurred_at"}
    assert detail["event_id"] == "a"
    assert detail["tracking_number"] == "MF0000000001"
    assert events.entries[0]["Source"] == "shiptrack.events"


def test_a_duplicate_is_not_announced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker_module, "apply_event", lambda *_: ApplyResult.DUPLICATE)
    events = FakeEvents()
    make(FakeSqs(body("a", Status.DELIVERED)), events).poll_once(0)
    assert events.entries == []


def test_put_events_is_retried_three_times_then_given_up(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker_module, "apply_event", lambda *_: ApplyResult.APPLIED)
    events = FakeEvents({"FailedEntryCount": 1}, {"FailedEntryCount": 1}, {"FailedEntryCount": 1})
    sqs = FakeSqs(body("a", Status.DELIVERED))
    make(sqs, events).poll_once(0)
    assert len(events.entries) == 3
    assert sqs.deleted == ["h0"]  # the data is committed; only the notification is lost


def test_put_events_recovers_on_the_second_try(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker_module, "apply_event", lambda *_: ApplyResult.APPLIED)
    events = FakeEvents({"FailedEntryCount": 1})
    make(FakeSqs(body("a", Status.DELIVERED)), events).poll_once(0)
    assert len(events.entries) == 2


def test_no_bus_means_no_announcements(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker_module, "apply_event", lambda *_: ApplyResult.APPLIED)
    events = FakeEvents()
    make(FakeSqs(body("a", Status.DELIVERED)), events, bus=None).poll_once(0)
    assert events.entries == []


def test_stop_ends_the_loop_after_the_poll_in_progress() -> None:
    class OneShot(QueueWorker):
        polls = 0

        def poll_once(self, wait_seconds: int = 20) -> int:
            self.polls += 1
            self.stop()
            return 0

        def handle(self, message: dict[str, Any]) -> bool:
            return True

    worker = OneShot("http://queue", sqs=FakeSqs())
    thread = threading.Thread(target=worker.run)
    thread.start()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert worker.polls == 1 and worker.stopping


def test_health_goes_bad_when_the_loop_stalls(monkeypatch: pytest.MonkeyPatch) -> None:
    worker = make(FakeSqs())
    assert worker.healthy()
    clock = iter([worker._last_beat + 121])
    monkeypatch.setattr(worker_module.time, "monotonic", lambda: next(clock))
    assert not worker.healthy()


def envelope(event_id: str, detail_type: str = "ShipmentDelivered") -> str:
    return json.dumps(
        {
            "detail-type": detail_type,
            "detail": {
                "event_id": event_id,
                "tracking_number": "MF0000000001",
                "status": "DELIVERED",
            },
        }
    )


def test_the_notifier_sends_each_event_once() -> None:
    sqs = FakeSqs(envelope("e1"), envelope("e1"), envelope("e2"))
    NotifyWorker("http://queue", sqs=sqs).poll_once(0)
    assert sqs.deleted == ["h0", "h1", "h2"]


def test_the_notifier_forgets_the_oldest_ids() -> None:
    worker = NotifyWorker("http://queue", sqs=FakeSqs())
    for i in range(NotifyWorker.CACHE_SIZE + 1):
        assert not worker._is_repeat(f"e{i}")
    assert not worker._is_repeat("e0")
    assert worker._is_repeat(f"e{NotifyWorker.CACHE_SIZE}")


def test_an_unreadable_notification_is_left_alone() -> None:
    sqs = FakeSqs("{}", "oops")
    NotifyWorker("http://queue", sqs=sqs).poll_once(0)
    assert sqs.deleted == []
