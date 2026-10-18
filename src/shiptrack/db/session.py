"""Engine and session helpers."""

from __future__ import annotations

from collections.abc import Callable, Iterator

import psycopg
import structlog
from fastapi import Request
from psycopg import errors as pg_errors
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from shiptrack.config import Settings
from shiptrack.secrets import DbCredentials, SecretCache

log = structlog.get_logger("shiptrack.db")

# 28P01 (wrong password) and 28000 (authorization failed): the signs of a rotated credential.
_AUTH_FAILURES = (pg_errors.InvalidPassword, pg_errors.InvalidAuthorizationSpecification)
_AUTH_SQLSTATES = frozenset({"28P01", "28000"})


def _is_auth_failure(error: psycopg.OperationalError) -> bool:
    """A login the server turned down for its credentials: what a rotated password looks like.

    A rejection while connecting is raised as a plain OperationalError, not as the class for
    its SQLSTATE: libpq gives psycopg the FATAL message and no result to read a code from. So
    the code is used when there is one, and the server's own wording when there is not.
    """
    return (
        isinstance(error, _AUTH_FAILURES)
        or error.sqlstate in _AUTH_SQLSTATES
        or "password authentication failed" in str(error)
    )


def _connect(credentials: DbCredentials, sslmode: str) -> psycopg.Connection[tuple[object, ...]]:
    return psycopg.connect(
        host=credentials.host,
        port=credentials.port,
        dbname=credentials.dbname,
        user=credentials.username,
        password=credentials.password,
        sslmode=sslmode,
        connect_timeout=10,
    )


def make_creator(
    settings: Settings, secret_arn: str, cache: SecretCache
) -> Callable[[], psycopg.Connection[tuple[object, ...]]]:
    """The function the pool calls for each new connection.

    It uses the secret's current credentials, and fetches the secret again, once, when the
    server turns them down.
    """

    def creator() -> psycopg.Connection[tuple[object, ...]]:
        try:
            return _connect(cache.get(secret_arn), settings.db_sslmode)
        except psycopg.OperationalError as error:
            if not _is_auth_failure(error):
                raise
            log.warning("db_auth_failed_refetching_secret")
            cache.invalidate(secret_arn)
            return _connect(cache.get(secret_arn), settings.db_sslmode)

    return creator


def create_db_engine(
    settings: Settings,
    secret_arn: str,
    cache: SecretCache,
    *,
    pool_size: int | None = None,
    max_overflow: int | None = None,
) -> Engine:
    """An engine whose connections use the secret's current credentials.

    The credentials are read for every new connection, so a refreshed secret reaches new
    connections. On an authentication failure the secret is fetched again once and the connection
    retried.
    """

    return create_engine(
        "postgresql+psycopg://",
        creator=make_creator(settings, secret_arn, cache),
        pool_pre_ping=True,
        pool_recycle=300,
        pool_size=settings.db_pool_size if pool_size is None else pool_size,
        max_overflow=settings.db_max_overflow if max_overflow is None else max_overflow,
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def get_session(request: Request) -> Iterator[Session]:
    factory: sessionmaker[Session] = request.app.state.session_factory
    with factory() as session:
        yield session
