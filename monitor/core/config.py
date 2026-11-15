"""
Central application configuration.

Everything that depends on *where* the application runs (database location,
server credentials, SQLite tuning) is resolved here, once.  No other module
may build a database URL on its own; they import :data:`settings`.

Two storage backends are supported:

* **SQLite** (default) - one file, no setup, used whenever
  ``NETSCOPE_DATABASE_URL`` is unset.
* **A server database** - anything SQLAlchemy can reach with a driver that is
  installed.  PostgreSQL through ``psycopg`` is the supported backend; see
  ``README.md`` for the one-time role/database setup.

Environment variables (all optional, prefix ``NETSCOPE_``):

    NETSCOPE_DATABASE_URL    Full SQLAlchemy URL, for example
                             ``postgresql+psycopg://user:pass@127.0.0.1:5432/netscope``.
                             When set, ``NETSCOPE_DATABASE_PATH`` is ignored.
    NETSCOPE_DATABASE_PATH   Absolute path to the SQLite file.
    NETSCOPE_PROJECT_ROOT    Project root used by default helpers.
    NETSCOPE_SQLITE_BUSY_TIMEOUT_MS
    NETSCOPE_ENABLE_WAL
    NETSCOPE_DB_POOL_SIZE    Server databases only (default 5).
    NETSCOPE_DB_MAX_OVERFLOW Server databases only (default 5).
    NETSCOPE_DB_POOL_RECYCLE Server databases only, seconds (default 1800).

Values may also be supplied through a ``.env`` file in the project root.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# ``config.py`` lives at <root>/monitor/core/config.py.
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# ``postgres://`` and ``postgresql://`` are the URLs people copy from hosting
# dashboards.  Both mean "PostgreSQL"; rewriting them to the installed driver
# avoids a confusing "module psycopg2 not found" error.
_POSTGRES_ALIASES = ("postgres://", "postgresql://")


class Settings(BaseSettings):
    """Immutable, validated application settings."""

    model_config = SettingsConfigDict(
        env_prefix="NETSCOPE_",
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    project_root: Path = Field(default=PROJECT_ROOT)

    # Full SQLAlchemy URL for an external database.  ``None`` means SQLite.
    database_url: str | None = Field(default=None)

    # Always stored as an absolute path so that starting the process from a
    # different working directory can never create a second database file.
    database_path: Path = Field(
        default=PROJECT_ROOT / "network_monitor.db"
    )

    sqlite_busy_timeout_ms: int = Field(default=5000, ge=0)
    enable_wal: bool = Field(default=True)

    # Server-database pooling.  The capture pipeline writes from a background
    # thread while API requests read, so a small pool is enough; recycling
    # guards against a server or firewall dropping idle connections.
    db_pool_size: int = Field(default=5, ge=1)
    db_max_overflow: int = Field(default=5, ge=0)
    db_pool_recycle: int = Field(default=1800, ge=-1)

    @field_validator("project_root", "database_path", mode="after")
    @classmethod
    def _resolve_absolute(cls, value: Path) -> Path:
        return value.expanduser().resolve()

    @field_validator("database_url", mode="after")
    @classmethod
    def _normalise_database_url(cls, value: str | None) -> str | None:
        if value is None:
            return None

        value = value.strip()

        if not value:
            return None

        if "://" not in value:
            raise ValueError(
                "NETSCOPE_DATABASE_URL must be a SQLAlchemy URL, e.g. "
                "postgresql+psycopg://user:password@127.0.0.1:5432/netscope"
            )

        for alias in _POSTGRES_ALIASES:
            if value.startswith(alias):
                return "postgresql+psycopg://" + value[len(alias):]

        return value

    @property
    def sqlalchemy_url(self) -> str:
        """The URL every engine, session and Alembic command must use."""

        if self.database_url:
            return self.database_url

        return f"sqlite:///{self.database_path.as_posix()}"

    @property
    def database_backend(self) -> str:
        """Driver-independent backend name, e.g. ``sqlite`` or ``postgresql``."""

        scheme = self.sqlalchemy_url.split("://", 1)[0]

        return scheme.split("+", 1)[0]

    @property
    def is_sqlite(self) -> bool:
        return self.database_backend == "sqlite"

    @property
    def safe_database_url(self) -> str:
        """The URL with any password replaced, safe to log or display."""

        url = self.sqlalchemy_url

        if "@" not in url or "://" not in url:
            return url

        scheme, remainder = url.split("://", 1)
        credentials, location = remainder.rsplit("@", 1)
        user = credentials.split(":", 1)[0]

        return f"{scheme}://{user}:***@{location}"


settings = Settings()

# Backwards-compatible module-level names.
DATABASE_PATH: Path = settings.database_path
DATABASE_URL: str = settings.sqlalchemy_url
