"""Create the application's database roles and schema (`python -m shiptrack db-init`).

The managed database is private and only the cluster can reach it, so the roles are created by a
Job running this image. It reads three credentials from the cloud's secret store: the
administrator's, which it connects with, and the passwords the application and the migrator will
use, which it sets on their roles. `db/init.sql` does the work and is safe to run again; running
it again with a new secret value is how a rotated password reaches the database.
"""

from __future__ import annotations

from pathlib import Path

import psycopg
import structlog

from shiptrack.config import Settings
from shiptrack.secrets import SecretCache

log = structlog.get_logger("shiptrack.db.init")


def run_db_init(settings: Settings, cache: SecretCache, script: Path | None = None) -> None:
    admin = cache.get(settings.require_admin_secret())
    app = cache.get(settings.require_db_secret())
    migrator = cache.get(settings.require_migrator_secret())
    sql = (script or settings.db_init_sql).read_text()

    log.info("db_init_started", admin=admin.username, host=admin.host, database=admin.dbname)
    with psycopg.connect(
        host=admin.host,
        port=admin.port,
        dbname=admin.dbname,
        user=admin.username,
        password=admin.password,
        sslmode=settings.db_sslmode,
        connect_timeout=10,
        autocommit=True,
    ) as connection:
        # Hand the values to the server session, where the script reads them. A statement with
        # parameters cannot hold several statements, so the script runs without any.
        for name, value in (
            ("shiptrack.app_password", app.password),
            ("shiptrack.migrator_password", migrator.password),
            ("shiptrack.app_connection_limit", str(settings.db_app_connection_limit)),
            ("shiptrack.migrator_connection_limit", str(settings.db_migrator_connection_limit)),
        ):
            connection.execute("SELECT set_config(%s, %s, false)", (name, value))
        connection.execute(sql)
    log.info("db_init_finished", roles=[app.username, migrator.username])
