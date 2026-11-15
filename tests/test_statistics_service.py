"""StatisticsService: live/database merge, caching, protocols and history."""

from __future__ import annotations

from datetime import datetime

from monitor.statistics.statistics_service import StatisticsService
from monitor.storage.database import SessionLocal
from monitor.storage.packet_repository import PacketRepository
from monitor.storage.statistics_repository import StatisticsRepository
from tests.helpers import packet_row, statistics_row


class FakeManager:
    """Stands in for CaptureManager so no socket is opened."""

    def __init__(self, snapshot=None, running=True):
        self._snapshot = snapshot or {}
        self._running = running

    def is_running(self):
        return self._running

    def snapshot(self):
        return dict(self._snapshot)


def _service(cache_ttl: float = 0.0):
    return StatisticsService(
        session_factory=SessionLocal, cache_ttl=cache_ttl
    )


def _seed(db, rows):
    PacketRepository(db).save_packets(rows)


def test_database_snapshot_when_capture_is_stopped(db):
    _seed(
        db,
        [
            packet_row(0, direction="outgoing", packet_size=100),
            packet_row(1, direction="incoming", packet_size=50),
            packet_row(2, direction="other", source_ip="10.0.0.1", packet_size=150),
        ],
    )

    snapshot = _service().current(None)

    assert snapshot["source"] == "database"
    assert snapshot["total_packets"] == 3
    assert snapshot["total_bytes"] == 300
    assert snapshot["average_packet_size"] == 100.0
    assert snapshot["upload_bytes"] == 100
    assert snapshot["download_bytes"] == 50
    assert snapshot["direction_counts"] == {"outgoing": 1, "incoming": 1, "other": 1}
    assert snapshot["unique_source_ips"] == 2
    assert snapshot["unique_destination_ips"] == 1
    assert snapshot["packets_per_second"] == 0.0


def test_empty_database_reports_empty_source(db):
    snapshot = _service().current(None)

    assert snapshot["source"] == "empty"
    assert snapshot["total_packets"] == 0
    assert snapshot["total_bytes"] == 0
    assert snapshot["average_packet_size"] == 0


def test_live_snapshot_comes_from_the_manager():
    manager = FakeManager(
        snapshot={
            "total_packets": 42,
            "total_bytes": 4200,
            "packets_per_second": 1.5,
            "upload_bytes_per_second": 10.0,
            "download_bytes_per_second": 20.0,
            "protocol_counts": {"TCP": 42},
            "top_talkers": [{"ip": "10.0.0.9", "packets": 42, "bytes": 4200}],
        }
    )

    snapshot = _service().current(manager)

    assert snapshot["source"] == "live"
    assert snapshot["total_packets"] == 42
    assert snapshot["protocol_counts"] == {"TCP": 42}
    assert snapshot["top_talkers"][0]["ip"] == "10.0.0.9"


def test_stopped_manager_falls_back_to_database(db):
    _seed(db, [packet_row(0, packet_size=10)])
    manager = FakeManager(snapshot={"total_packets": 999}, running=False)

    snapshot = _service().current(manager)

    assert snapshot["source"] == "database"
    assert snapshot["total_packets"] == 1


def test_protocol_percentages_are_derived_from_totals(db):
    _seed(
        db,
        [
            packet_row(0, protocol="TCP", application_protocol="HTTPS/TLS"),
            packet_row(1, protocol="TCP", application_protocol="HTTPS/TLS"),
            packet_row(2, protocol="TCP", application_protocol="DNS"),
            packet_row(3, protocol="UDP", application_protocol="DNS"),
        ],
    )

    payload = _service().protocols()

    assert payload["total_packets"] == 4

    transport = {
        row["protocol"]: row for row in payload["protocols"]
    }
    application = {
        row["protocol"]: row for row in payload["application_protocols"]
    }

    assert transport["TCP"]["packets"] == 3
    assert transport["TCP"]["percentage"] == 75.0
    assert transport["UDP"]["percentage"] == 25.0

    assert application["DNS"]["packets"] == 2
    assert application["DNS"]["percentage"] == 50.0


def test_protocols_on_empty_database_has_zero_percentages(db):
    payload = _service().protocols()

    assert payload["total_packets"] == 0
    assert payload["protocols"] == []
    assert payload["application_protocols"] == []


def test_database_snapshot_is_cached(db):
    _seed(db, [packet_row(0, packet_size=10)])
    service = _service(cache_ttl=60)

    first = service.current(None)
    _seed(db, [packet_row(1, packet_size=10)])
    second = service.current(None)

    assert first["total_packets"] == 1
    assert second["total_packets"] == 1

    service.clear_cache()

    assert service.current(None)["total_packets"] == 2


def test_cache_can_be_disabled(db):
    _seed(db, [packet_row(0, packet_size=10)])
    service = _service(cache_ttl=0)

    assert service.current(None)["total_packets"] == 1

    _seed(db, [packet_row(1, packet_size=10)])

    assert service.current(None)["total_packets"] == 2


def test_history_and_top_talkers_delegate_to_repositories(db):
    _seed(
        db,
        [
            packet_row(0, source_ip="10.0.0.1", packet_size=300),
            packet_row(1, source_ip="10.0.0.2", packet_size=100),
        ],
    )

    session = SessionLocal()

    try:
        StatisticsRepository(session).add_snapshot(
            statistics_row(0), timestamp=datetime(2026, 1, 1, 0, 0, 0)
        )
        StatisticsRepository(session).add_snapshot(
            statistics_row(1), timestamp=datetime(2026, 1, 1, 0, 0, 5)
        )
    finally:
        session.close()

    service = _service()

    history = service.history(limit=10)
    assert [row.total_packets for row in history] == [101, 100]

    talkers = service.top_talkers(limit=1)
    assert talkers == [{"ip": "10.0.0.1", "packets": 1, "bytes": 300}]
