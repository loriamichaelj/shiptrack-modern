"""SLA breach scan, run by a single Kubernetes CronJob (REM-09).

The whole scan is one statement: it flags every overdue, undelivered, not-yet-flagged shipment and
records an alert for exactly those rows. Two scanners that run at once cannot both flag the same
shipment, because the second UPDATE waits for the first and then no longer matches the WHERE clause.
So the result is correct however many scanners run, and the CronJob's `concurrencyPolicy: Forbid`
is a second guard and not the only one.
"""

from __future__ import annotations

import os
import socket
import sys
import time
from typing import NamedTuple

import structlog
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from shiptrack import metrics
from shiptrack.config import load_settings
from shiptrack.db.session import create_db_engine, create_session_factory
from shiptrack.domain.models import format_utc
from shiptrack.logconfig import configure_logging
from shiptrack.secrets import SecretCache

log = structlog.get_logger("shiptrack.sla")

SCAN_SQL = text(
    """
    WITH breached AS (
      UPDATE shiptrack.shipments
         SET sla_breached = true, sla_breached_at = now(), updated_at = now()
       WHERE status <> 'DELIVERED' AND promised_delivery_at < now() AND NOT sla_breached
      RETURNING id, tracking_number, promised_delivery_at
    ), alerted AS (
      INSERT INTO shiptrack.sla_alerts (shipment_id, detected_by)
      SELECT id, :pod_name FROM breached
      RETURNING shipment_id
    )
    SELECT tracking_number, promised_delivery_at FROM breached
    """
)


class Breach(NamedTuple):
    tracking_number: str
    promised_delivery_at: str


def pod_name() -> str:
    return os.environ.get("HOSTNAME") or socket.gethostname()


def run_scan(session_factory: sessionmaker[Session], detected_by: str) -> list[Breach]:
    """Flag and alert on every overdue shipment, in one transaction; return what was flagged."""
    started = time.monotonic()
    with session_factory() as session:
        rows = session.execute(SCAN_SQL, {"pod_name": detected_by}).all()
        session.commit()
    breaches = [Breach(r.tracking_number, format_utc(r.promised_delivery_at)) for r in rows]
    for breach in breaches:
        log.info(
            "sla_breach",
            tracking_number=breach.tracking_number,
            promised=breach.promised_delivery_at,
            detected_by=detected_by,
        )
    metrics.SLA_BREACHES.inc(len(breaches))
    # This record is also the heartbeat the "scan has stopped running" alarm watches for.
    log.info(
        "sla_scan_completed",
        breaches=len(breaches),
        duration_ms=round((time.monotonic() - started) * 1000, 1),
    )
    return breaches


def main() -> int:
    settings = load_settings()
    configure_logging(settings.log_level)
    engine = create_db_engine(
        settings,
        settings.require_db_secret(),
        SecretCache(settings.aws_region),
        pool_size=1,
        max_overflow=1,
    )
    try:
        run_scan(create_session_factory(engine), pod_name())
    except Exception:
        log.exception("sla_scan_failed")
        return 1
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
