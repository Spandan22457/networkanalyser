"""
Database engine, session factory and declarative base.

SQLAlchemy 2.x style.  The database location comes exclusively from
:mod:`monitor.core.config`, so the file is the same no matter which directory
the process was started from.

SQLite is configured once per connection:

* ``journal_mode=WAL``     concurrent readers while the writer commits
* ``busy_timeout``         wait instead of raising "database is locked"
* ``foreign_keys=ON``      enforce relationships
* ``synchronous=NORMAL``   safe with WAL, much faster than FULL
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from monitor.core.config import settings


# Backwards-compatible re-exports (older scripts imported these from here).
DATABASE_PATH = settings.database_path
DATABASE_URL = settings.database_url


class Base(DeclarativeBase):
    """Declarative base shared by every ORM model."""


engine = create_engine(
    settings.database_url,
    connect_args={
        "check_same_thread": False,
        "timeout": settings.sqlite_busy_timeout_ms / 1000,
    },
    pool_pre_ping=True,
    future=True,
)


@event.listens_for(engine, "connect")
def _configure_sqlite_connection(dbapi_connection, _connection_record) -> None:
    """Apply the SQLite pragmas to every new connection."""

    cursor = dbapi_connection.cursor()

    try:
        if settings.enable_wal:
            # Returns the resulting mode, which may differ on network shares.
            cursor.execute("PRAGMA journal_mode=WAL")

        cursor.execute(
            f"PRAGMA busy_timeout={settings.sqlite_busy_timeout_ms}"
        )
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA synchronous=NORMAL")

    finally:
        cursor.close()


SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    future=True,
)


def import_models() -> None:
    """Import every model module so mappings are registered on ``Base``."""

    # Imported for the side effect of registering the mappings.
    from monitor.storage import models  # noqa: F401


def init_database() -> None:
    """
    Create any missing tables and indexes.

    Idempotent.  This does **not** alter existing tables; schema changes to a
    populated database are applied with Alembic (``alembic upgrade head``).
    """

    import_models()
    Base.metadata.create_all(bind=engine)


def create_session() -> Session:
    """Create a standalone session for background workers/tests."""

    return SessionLocal()


def get_db() -> Iterator[Session]:
    """FastAPI dependency that yields a session and always closes it."""

    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()
