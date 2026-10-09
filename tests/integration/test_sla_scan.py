"""REM-09: one atomic statement, correct however many scanners run."""

import threading
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from shiptrack.config import Settings
from shiptrack.db.session import create_db_engine, create_session_factory
from shiptrack.jobs.sla_scan import run_scan
from shiptrack.secrets import SecretCache

from .conftest import NOW

MakeShipment = Callable[..., dict[str, Any]]
SendEvent = Callable[..., Any]
PAST = NOW - timedelta(days=2)
FUTURE = NOW + timedelta(days=2)


def alerts(engine: Engine) -> list[Any]:
    with engine.connect() as connection:
        return list(
            connection.execute(
                text("SELECT shipment_id::text, detected_by FROM shiptrack.sla_alerts ORDER BY id")
            )
        )


@pytest.fixture()
def factory(settings: Settings) -> sessionmaker[Session]:
    return create_session_factory(
        create_db_engine(settings, settings.require_db_secret(), SecretCache(), pool_size=1)
    )


def test_overdue_shipments_are_flagged_and_alerted(
    engine: Engine,
    factory: sessionmaker[Session],
    make_shipment: MakeShipment,
    send_event: SendEvent,
) -> None:
    overdue = make_shipment(promised=PAST)
    make_shipment(promised=FUTURE)  # not due yet
    delivered = make_shipment(promised=PAST)
    send_event(delivered["id"], "DELIVERED", NOW - timedelta(days=3))

    breaches = run_scan(factory, "pod-a")

    assert [b.tracking_number for b in breaches] == [overdue["tracking_number"]]
    assert alerts(engine) == [(overdue["id"], "pod-a")]
    with engine.connect() as connection:
        flagged = connection.execute(
            text(
                "SELECT id::text FROM shiptrack.shipments "
                "WHERE sla_breached AND sla_breached_at IS NOT NULL"
            )
        ).all()
    assert [row[0] for row in flagged] == [overdue["id"]]


def test_a_flagged_shipment_is_not_alerted_again(
    engine: Engine, factory: sessionmaker[Session], make_shipment: MakeShipment
) -> None:
    make_shipment(promised=PAST)
    assert len(run_scan(factory, "pod-a")) == 1
    assert run_scan(factory, "pod-b") == []
    assert len(alerts(engine)) == 1


def test_a_scan_with_nothing_to_do_reports_zero(factory: sessionmaker[Session]) -> None:
    assert run_scan(factory, "pod-a") == []


def test_concurrent_scanners_raise_exactly_one_alert_per_breach(
    settings: Settings, engine: Engine, make_shipment: MakeShipment
) -> None:
    """The AP-09 evidence: with the legacy read-then-write, two scanners alerted twice."""
    for _ in range(30):
        make_shipment(promised=PAST)
    scanners = 6
    factories = [
        create_session_factory(
            create_db_engine(settings, settings.require_db_secret(), SecretCache(), pool_size=1)
        )
        for _ in range(scanners)
    ]
    start = threading.Barrier(scanners)
    flagged: list[int] = []
    errors: list[BaseException] = []

    def scan(index: int) -> None:
        try:
            start.wait(timeout=10)
            flagged.append(len(run_scan(factories[index], f"pod-{index}")))
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=scan, args=(i,)) for i in range(scanners)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert not errors
    assert sum(flagged) == 30
    rows = alerts(engine)
    assert len(rows) == 30
    assert len({shipment_id for shipment_id, _ in rows}) == 30


def test_breaches_are_logged(
    factory: sessionmaker[Session], make_shipment: MakeShipment, caplog: pytest.LogCaptureFixture
) -> None:
    shipment = make_shipment(promised=PAST)
    with caplog.at_level("INFO", logger="shiptrack.sla"):
        run_scan(factory, "pod-a")
    text_ = "\n".join(record.message for record in caplog.records)
    assert "sla_breach" in text_ and shipment["tracking_number"] in text_
    assert "sla_scan_completed" in text_
