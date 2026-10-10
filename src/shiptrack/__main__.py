"""One image, several processes: `python -m shiptrack <command>` (design 5.3)."""

from __future__ import annotations

import argparse
import signal
import sys
from types import FrameType

import structlog
import uvicorn

from shiptrack.config import ConfigError, Settings, load_settings
from shiptrack.db.session import create_db_engine, create_session_factory
from shiptrack.events.worker import EventWorker, NotifyWorker, QueueWorker
from shiptrack.logconfig import configure_logging
from shiptrack.ops import start_ops_server
from shiptrack.secrets import SecretCache

log = structlog.get_logger("shiptrack")

API_PORT = 8000
OPS_PORT = 9090
COMMANDS = ("api", "worker-events", "worker-notify", "sla-scan", "migrate")


class DrainingServer(uvicorn.Server):
    """Stop being ready as soon as SIGTERM arrives, then let uvicorn finish in-flight requests."""

    def handle_exit(self, sig: int, frame: FrameType | None) -> None:
        readiness = (
            getattr(self.config.loaded_app.state, "readiness", None) if self.config.loaded else None
        )
        if readiness is not None:
            readiness.drain()
            log.info("draining")
        super().handle_exit(sig, frame)


def serve_api(settings: Settings) -> int:
    configure_logging(settings.log_level)
    start_ops_server(OPS_PORT)
    config = uvicorn.Config(
        "shiptrack.main:app",
        host="0.0.0.0",
        port=API_PORT,
        proxy_headers=True,
        forwarded_allow_ips="*",
        log_config=None,
        access_log=False,
        timeout_graceful_shutdown=30,
    )
    DrainingServer(config).run()
    return 0


def run_worker(worker: QueueWorker) -> int:
    def stop(signum: int, _: FrameType | None) -> None:
        log.info("stopping", signal=signal.Signals(signum).name)
        worker.stop()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    start_ops_server(OPS_PORT, worker.healthy)
    worker.run()
    return 0


def serve_worker_events(settings: Settings) -> int:
    configure_logging(settings.log_level)
    engine = create_db_engine(
        settings, settings.require_db_secret(), SecretCache(settings.aws_region)
    )
    worker = EventWorker(
        settings.require_events_queue(),
        create_session_factory(engine),
        bus_name=settings.event_bus_name,
        region=settings.aws_region,
    )
    try:
        return run_worker(worker)
    finally:
        engine.dispose()


def serve_worker_notify(settings: Settings) -> int:
    configure_logging(settings.log_level)
    return run_worker(NotifyWorker(settings.require_notify_queue(), settings.aws_region))


def migrate(settings: Settings) -> int:
    """Run the Alembic migrations as shiptrack_migrator, and only when ownership allows it."""
    configure_logging(settings.log_level)
    if not settings.migrations_enabled:
        log.error(
            "migrations_disabled", hint="set SHIPTRACK_MIGRATIONS_ENABLED=true after the handoff"
        )
        return 2
    from alembic import command
    from alembic.config import Config

    log.info("migrations_started")
    command.upgrade(Config("alembic.ini"), "head")
    log.info("migrations_finished")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m shiptrack", description=__doc__)
    parser.add_argument("command", nargs="?", default="api", choices=COMMANDS)
    args = parser.parse_args(argv)
    try:
        settings = load_settings()
        if args.command == "api":
            return serve_api(settings)
        if args.command == "worker-events":
            return serve_worker_events(settings)
        if args.command == "worker-notify":
            return serve_worker_notify(settings)
        if args.command == "migrate":
            return migrate(settings)
        from shiptrack.jobs.sla_scan import main as sla_scan

        return sla_scan()
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
