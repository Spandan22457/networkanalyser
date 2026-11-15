"""
Shared test configuration.

The database path is redirected to a throwaway directory *before* any project
module is imported, so no test can ever touch network_monitor.db.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

# ``mkdtemp`` can return a Windows short (8.3) path; resolve it so the value
# matches what the settings validator produces.
TEST_ROOT = Path(tempfile.mkdtemp(prefix="netscope-tests-")).resolve()

os.environ["NETSCOPE_DATABASE_PATH"] = str(TEST_ROOT / "test.db")
os.environ["NETSCOPE_ENABLE_WAL"] = "0"
# A developer's .env may point NETSCOPE_DATABASE_URL at a real PostgreSQL
# server.  The suite must never touch it, so the override is cleared here.
os.environ["NETSCOPE_DATABASE_URL"] = ""

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from monitor.core.config import settings  # noqa: E402
from monitor.statistics.statistics_service import statistics_service  # noqa: E402
from monitor.storage.database import SessionLocal, init_database  # noqa: E402
from monitor.storage.models import (  # noqa: E402
    ConnectionRecord,
    NetworkStatistics,
    PacketRecord,
)
from tests.helpers import packet_row  # noqa: E402,F401


@pytest.fixture(scope="session", autouse=True)
def _schema():
    assert settings.database_path == TEST_ROOT / "test.db"
    assert settings.is_sqlite, "tests must never run against a server database"
    init_database()
    yield


@pytest.fixture(autouse=True)
def clean_database(_schema):
    """Every test starts from empty tables, never from another test's rows."""

    session = SessionLocal()

    try:
        session.query(ConnectionRecord).delete()
        session.query(NetworkStatistics).delete()
        session.query(PacketRecord).delete()
        session.commit()

    finally:
        session.close()

    # The read model caches database aggregates for a few seconds; without
    # this a later test could see the previous test's totals.
    statistics_service.clear_cache()

    yield

    statistics_service.clear_cache()


@pytest.fixture()
def db():
    session = SessionLocal()

    try:
        yield session

    finally:
        session.close()


@pytest.fixture(scope="session")
def client():
    from api.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def packet_batch():
    return [packet_row(index) for index in range(5)]
