"""Alembic environment.

Connection resolution, in order:
1. a connection passed in by the caller (`config.attributes["connection"]`), used by tests;
2. the migrator credentials from Secrets Manager (`SHIPTRACK_DB_MIGRATOR_SECRET_ARN`), used by the
   `migrate` command (REM-02: migrations run as `shiptrack_migrator`, the application as `shiptrack_app`).
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import text
from sqlalchemy.engine import Connection

from shiptrack.config import load_settings
from shiptrack.db.models import SCHEMA, Base
from shiptrack.db.session import create_db_engine
from shiptrack.secrets import SecretCache

config = context.config
target_metadata = Base.metadata


def _ensure_schema(connection: Connection) -> None:
    # The schema is normally created by db/bootstrap.sql and owned by the migrator role, which
    # may not hold CREATE on the database, so only create it when it is missing.
    exists = connection.scalar(
        text("SELECT 1 FROM information_schema.schemata WHERE schema_name = :name"),
        {"name": SCHEMA},
    )
    if not exists:
        connection.execute(text(f'CREATE SCHEMA "{SCHEMA}"'))
    connection.commit()


def _run(connection: Connection) -> None:
    _ensure_schema(connection)
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table_schema=SCHEMA,
        include_schemas=False,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _run(connection)
        return
    settings = load_settings()
    engine = create_db_engine(
        settings,
        settings.require_migrator_secret(),
        SecretCache(settings.aws_region),
        pool_size=1,
        max_overflow=1,
    )
    try:
        with engine.connect() as conn:
            _run(conn)
    finally:
        engine.dispose()


run_migrations_online()
