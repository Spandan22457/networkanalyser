"""
Central application configuration.

Everything that depends on *where* the application runs (database location,
SQLite tuning) is resolved here, once, from absolute paths.  No other module
may build a database path on its own; they import :data:`settings`.

Environment variables (all optional, prefix ``NETSCOPE_``):

    NETSCOPE_DATABASE_PATH   Absolute path to the SQLite file.
    NETSCOPE_PROJECT_ROOT    Project root used by default helpers.
    NETSCOPE_SQLITE_BUSY_TIMEOUT_MS
    NETSCOPE_ENABLE_WAL

Values may also be supplied through a ``.env`` file in the project root.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# ``config.py`` lives at <root>/monitor/core/config.py.
PROJECT_ROOT = Path(__file__).resolve().parents[2]


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

    # Always stored as an absolute path so that starting the process from a
    # different working directory can never create a second database file.
    database_path: Path = Field(
        default=PROJECT_ROOT / "network_monitor.db"
    )

    sqlite_busy_timeout_ms: int = Field(default=5000, ge=0)
    enable_wal: bool = Field(default=True)

    @field_validator("project_root", "database_path", mode="after")
    @classmethod
    def _resolve_absolute(cls, value: Path) -> Path:
        return value.expanduser().resolve()

    @property
    def database_url(self) -> str:
        """SQLAlchemy URL for the configured SQLite file."""

        return f"sqlite:///{self.database_path.as_posix()}"


settings = Settings()

# Backwards-compatible module-level names.
DATABASE_PATH: Path = settings.database_path
DATABASE_URL: str = settings.database_url
