"""`python -m shiptrack db-init` creates the application's roles and schema (db/init.sql)."""

import json
import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from psycopg import errors as pg_errors
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import URL, make_url

from shiptrack.config import Settings
from shiptrack.db.init import run_db_init
from shiptrack.secrets import SecretCache

from .conftest import ADMIN_URL, ROOT

SCRIPT = ROOT / "db" / "init.sql"
ADMIN_PASSWORD = "admin-pw"

# Roles belong to the whole server, and db-init creates them, so each test starts without them and
# removes its database and them afterwards. An administrator can only change roles it created.
ROLES = (
    "shiptrack_app",
    "shiptrack_migrator",
    "init_admin",
    "init_member",
    "init_guest",
    "owner_group",
)


@pytest.fixture()
def url(admin_engine: Engine) -> Iterator[URL]:
    name = f"shiptrack_init_{uuid.uuid4().hex[:10]}"

    def drop_roles() -> None:
        with admin_engine.connect() as connection:
            for role in ROLES:
                connection.execute(text(f"DROP ROLE IF EXISTS {role}"))

    drop_roles()
    with admin_engine.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    yield make_url(ADMIN_URL).set(database=name)
    with admin_engine.connect() as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    drop_roles()


class DictSource:
    def __init__(self, secrets: dict[str, dict[str, object]]) -> None:
        self._secrets = secrets

    def fetch(self, name: str) -> str:
        return json.dumps(self._secrets[name])


def secret(url: URL, username: str, password: str) -> dict[str, object]:
    return {
        "username": username,
        "password": password,
        "host": url.host,
        "port": url.port or 5432,
        "dbname": url.database,
        "engine": "postgres",
    }


def init(
    url: URL, admin: str, admin_password: str, app_password: str, migrator_password: str
) -> None:
    source = DictSource(
        {
            "admin": secret(url, admin, admin_password),
            "app": secret(url, "shiptrack_app", app_password),
            "migrator": secret(url, "shiptrack_migrator", migrator_password),
        }
    )
    settings = Settings(
        db_admin_secret_arn="admin",
        db_secret_arn="app",
        db_migrator_secret_arn="migrator",
        db_sslmode="disable",
        db_app_connection_limit=18,
        db_migrator_connection_limit=3,
    )
    run_db_init(settings, SecretCache(source=source), SCRIPT)


def connect(url: URL, user: str, password: str) -> psycopg.Connection[tuple[object, ...]]:
    return psycopg.connect(
        host=url.host,
        port=url.port or 5432,
        dbname=url.database,
        user=user,
        password=password,
        sslmode="disable",
        autocommit=True,
        connect_timeout=5,
    )


def as_postgres(statement: str) -> None:
    engine = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with engine.connect() as connection:
        connection.execute(text(statement))
    engine.dispose()


def make_admin(name: str) -> None:
    """A login role that is not a superuser, as an RDS master or a Cloud SQL administrator is."""
    as_postgres(
        f"""DO $$ BEGIN
          IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{name}') THEN
            CREATE ROLE {name} LOGIN CREATEROLE PASSWORD '{ADMIN_PASSWORD}';
          END IF; END $$"""
    )


def check_roles_and_grants(url: URL, app_password: str, migrator_password: str) -> None:
    with connect(url, "shiptrack_migrator", migrator_password) as migrator:
        migrator.execute("CREATE TABLE shiptrack.things (id serial PRIMARY KEY, name text)")
        owner = migrator.execute(
            "SELECT nspowner::regrole::text FROM pg_namespace WHERE nspname = 'shiptrack'"
        ).fetchone()
        assert owner == ("shiptrack_migrator",)
    with connect(url, "shiptrack_app", app_password) as app:
        # A table the migrator created later is usable with no new grant (default privileges).
        app.execute("INSERT INTO shiptrack.things (name) VALUES ('a')")
        assert app.execute("SELECT count(*) FROM shiptrack.things").fetchone() == (1,)
        with pytest.raises(pg_errors.InsufficientPrivilege):
            app.execute("CREATE TABLE shiptrack.other (id int)")
        with pytest.raises(pg_errors.InsufficientPrivilege):
            app.execute("CREATE TABLE public.other (id int)")
        with pytest.raises(pg_errors.InsufficientPrivilege):
            app.execute("DROP TABLE shiptrack.things")


def test_a_superuser_admin_creates_the_roles_and_the_schema(url: URL) -> None:
    init(url, "postgres", "postgres", "app-pw-1", "migrator-pw-1")
    check_roles_and_grants(url, "app-pw-1", "migrator-pw-1")


def test_a_second_run_with_new_passwords_rotates_them(url: URL) -> None:
    init(url, "postgres", "postgres", "app-pw-1", "migrator-pw-1")
    init(url, "postgres", "postgres", "app-pw-2", "migrator-pw-2")
    with pytest.raises(pg_errors.OperationalError):
        connect(url, "shiptrack_app", "app-pw-1")
    with connect(url, "shiptrack_app", "app-pw-2") as app:
        assert app.execute("SELECT 1").fetchone() == (1,)
    with connect(url, "shiptrack_migrator", "migrator-pw-2") as migrator:
        assert migrator.execute("SELECT 1").fetchone() == (1,)


def test_the_connection_limits_come_from_the_settings(url: URL) -> None:
    init(url, "postgres", "postgres", "app-pw-1", "migrator-pw-1")
    with connect(url, "shiptrack_app", "app-pw-1") as app:
        limits = app.execute(
            "SELECT rolname, rolconnlimit FROM pg_roles WHERE rolname LIKE 'shiptrack_%' "
            "ORDER BY rolname"
        ).fetchall()
    assert limits == [("shiptrack_app", 18), ("shiptrack_migrator", 3)]


def test_an_administrator_who_owns_the_database_is_enough(url: URL) -> None:
    make_admin("init_admin")
    as_postgres(f'ALTER DATABASE "{url.database}" OWNER TO init_admin')
    init(url, "init_admin", ADMIN_PASSWORD, "app-pw-1", "migrator-pw-1")
    check_roles_and_grants(url, "app-pw-1", "migrator-pw-1")
    init(url, "init_admin", ADMIN_PASSWORD, "app-pw-1", "migrator-pw-1")  # and again


def test_an_administrator_in_the_owning_group_is_enough(url: URL) -> None:
    # A managed service makes a group role the owner, and the administrator a member of it.
    make_admin("init_member")
    as_postgres(
        "DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'owner_group') THEN "
        "CREATE ROLE owner_group NOLOGIN; END IF; END $$"
    )
    as_postgres("GRANT owner_group TO init_member")
    as_postgres(f'ALTER DATABASE "{url.database}" OWNER TO owner_group')
    init(url, "init_member", ADMIN_PASSWORD, "app-pw-1", "migrator-pw-1")
    check_roles_and_grants(url, "app-pw-1", "migrator-pw-1")


def test_an_administrator_who_cannot_change_the_owner_still_finishes(url: URL) -> None:
    make_admin("init_guest")
    as_postgres(f'GRANT CREATE ON DATABASE "{url.database}" TO init_guest')
    init(url, "init_guest", ADMIN_PASSWORD, "app-pw-1", "migrator-pw-1")
    check_roles_and_grants(url, "app-pw-1", "migrator-pw-1")


def test_the_script_holds_no_password() -> None:
    sql = Path(SCRIPT).read_text()
    assert "PASSWORD '" not in sql
    assert "current_setting('shiptrack.app_password')" in sql
