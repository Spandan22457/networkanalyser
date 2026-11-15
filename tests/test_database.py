"""Schema and configuration invariants."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import inspect, text

from monitor.core.config import settings
from monitor.storage.database import engine, init_database
from monitor.storage.models import (
    ConnectionRecord,
    NetworkStatistics,
    PacketRecord,
)


SQLITE = settings.is_sqlite

FLOW_KEY = (
    "source_ip",
    "destination_ip",
    "source_port",
    "destination_port",
    "protocol",
)


def test_database_path_is_absolute_and_isolated():
    assert isinstance(settings.database_path, Path)
    assert settings.database_path.is_absolute()
    assert settings.database_path.name == "test.db"
    assert "netscope-tests-" in str(settings.database_path)


def test_database_url_points_at_configured_file():
    assert SQLITE
    assert settings.database_url is None
    assert settings.database_backend == "sqlite"
    assert settings.sqlalchemy_url.startswith("sqlite:///")
    assert settings.database_path.as_posix() in settings.sqlalchemy_url


def test_engine_dialect_matches_the_configured_backend():
    assert engine.dialect.name == settings.database_backend


def test_init_database_is_idempotent():
    init_database()
    init_database()

    tables = set(inspect(engine).get_table_names())

    assert {
        PacketRecord.__tablename__,
        NetworkStatistics.__tablename__,
        ConnectionRecord.__tablename__,
    } <= tables


def test_packet_table_has_metadata_columns_only():
    columns = {
        column["name"]
        for column in inspect(engine).get_columns("packets")
    }

    assert {
        "timestamp",
        "source_ip",
        "destination_ip",
        "source_mac",
        "destination_mac",
        "source_port",
        "destination_port",
        "protocol",
        "application_protocol",
        "packet_size",
        "tcp_flags",
        "direction",
        "ip_version",
        "interface",
    } <= columns

    # No payload column may ever be added to this table.
    assert not {"payload", "raw", "raw_bytes", "data"} & columns


def test_connection_flow_unique_constraint_exists():
    """Works on both backends, unlike the SQLite-only PRAGMA version."""

    constraints = inspect(engine).get_unique_constraints("connections")
    keys = {tuple(sorted(constraint["column_names"])) for constraint in constraints}

    assert tuple(sorted(FLOW_KEY)) in keys


@pytest.mark.skipif(not SQLITE, reason="SQLite pragmas only")
def test_sqlite_pragmas_are_applied():
    with engine.connect() as connection:
        busy_timeout = connection.execute(
            text("PRAGMA busy_timeout")
        ).scalar_one()
        foreign_keys = connection.execute(
            text("PRAGMA foreign_keys")
        ).scalar_one()

    assert int(busy_timeout) == settings.sqlite_busy_timeout_ms
    assert int(foreign_keys) == 1
