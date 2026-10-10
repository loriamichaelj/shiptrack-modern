"""Readiness (REM-07): can this pod take traffic right now?

/healthz never looks at a dependency. /readyz does, and answers 503 when the pod is draining, when a
game day forces it, when the database is at a schema revision this build does not tolerate (design
9.1), or when `SELECT 1` does not come back within a second. The answer is cached for two seconds so
a probe storm does not become a query storm.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass

import structlog
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from shiptrack.config import Settings

log = structlog.get_logger("shiptrack.ready")

PROBE_TIMEOUT_SECONDS = 1.0
CACHE_SECONDS = 2.0
ALEMBIC_VERSION_SQL = text("SELECT version_num FROM shiptrack.alembic_version")


@dataclass(frozen=True)
class Readiness:
    ready: bool
    reason: str


class ReadinessProbe:
    def __init__(self, session_factory: sessionmaker[Session], settings: Settings) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="readyz")
        self._lock = threading.Lock()
        self._cached: tuple[float, Readiness] | None = None
        self.draining = False

    def drain(self) -> None:
        """Called on SIGTERM: stop being ready so the load balancer moves traffic away."""
        self.draining = True

    def check(self) -> Readiness:
        if self.draining:
            return Readiness(False, "draining")
        if self._settings.fault_ready_fail:
            return Readiness(False, "fault_injected")
        with self._lock:
            if self._cached and time.monotonic() - self._cached[0] < CACHE_SECONDS:
                return self._cached[1]
        result = self._probe()
        with self._lock:
            self._cached = (time.monotonic(), result)
        return result

    def _query_revision(self) -> str | None:
        with self._session_factory() as session:
            session.execute(text("SET LOCAL statement_timeout = 1000"))
            revision = session.scalar(ALEMBIC_VERSION_SQL)
            return None if revision is None else str(revision)

    def _probe(self) -> Readiness:
        future = self._executor.submit(self._query_revision)
        try:
            revision = future.result(timeout=PROBE_TIMEOUT_SECONDS)
        except FutureTimeout:
            return Readiness(False, "database_timeout")
        except Exception as exc:
            log.warning("database_unavailable", error=type(exc).__name__)
            return Readiness(False, "database_unavailable")
        compatible = self._settings.schema_compat_revisions
        if compatible and revision not in compatible:
            log.error(
                "schema_incompatible",
                revision=revision,
                tolerated=sorted(compatible),
            )
            return Readiness(False, "schema_incompatible")
        return Readiness(True, "ok")
