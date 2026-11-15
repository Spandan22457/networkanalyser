"""Capture pipeline: flow aggregation, retries, dead-letter and the writer thread."""

from __future__ import annotations

import json
import threading

from monitor.capture.capture_manager import CaptureManager
from monitor.capture.connection_tracker import build_flows
from monitor.storage.database import SessionLocal
from monitor.storage.dead_letter import DeadLetterWriter
from monitor.storage.models import ConnectionRecord, NetworkStatistics, PacketRecord
from monitor.storage.statistics_repository import StatisticsRepository
from tests.helpers import packet_row


class StubPacketRepository:
    """Records calls and fails a configurable number of times."""

    def __init__(self, failures: int = 0, result: int = 1):
        self.failures = failures
        self.result = result
        self.calls = 0

    def save_packets(self, batch):
        self.calls += 1

        if self.calls <= self.failures:
            raise RuntimeError("simulated database failure")

        return self.result


def _manager(tmp_path, **kwargs):
    return CaptureManager(
        interface="Test Interface",
        dead_letter=DeadLetterWriter(tmp_path / "dead.jsonl"),
        **kwargs,
    )


def test_build_flows_groups_by_five_tuple():
    packets = [
        packet_row(0, packet_size=100),
        packet_row(0, packet_size=50),
        packet_row(1, packet_size=70),
    ]

    flows = build_flows(packets)

    assert len(flows) == 2

    first = next(flow for flow in flows if flow["source_port"] == 40000)
    assert first["packet_count"] == 2
    assert first["byte_count"] == 150
    assert first["protocol"] == "UDP"
    assert first["state"] == "OPEN"


def test_build_flows_tracks_first_and_last_seen():
    packets = [
        packet_row(0, timestamp="2026-01-01T00:00:05+00:00"),
        packet_row(0, timestamp="2026-01-01T00:00:01+00:00"),
        packet_row(0, timestamp="2026-01-01T00:00:09+00:00"),
    ]

    flow = build_flows(packets)[0]

    assert flow["first_seen"].isoformat().startswith("2026-01-01T00:00:01")
    assert flow["last_seen"].isoformat().startswith("2026-01-01T00:00:09")
    assert flow["first_seen"] <= flow["last_seen"]


def test_build_flows_tcp_state_from_flags():
    established = build_flows(
        [packet_row(0, protocol="TCP", tcp_flags="S")]
    )[0]
    closed = build_flows(
        [packet_row(0, protocol="TCP", tcp_flags="FA")]
    )[0]
    reset = build_flows(
        [packet_row(0, protocol="TCP", tcp_flags="R")]
    )[0]

    assert established["state"] == "ESTABLISHED"
    assert closed["state"] == "CLOSED"
    assert reset["state"] == "CLOSED"


def test_save_packets_retries_once_then_succeeds(tmp_path):
    manager = _manager(tmp_path)
    repository = StubPacketRepository(failures=1, result=5)

    assert manager._save_packets([packet_row(0)], repository) == 5
    assert repository.calls == 2
    assert manager.status()["storage_failed_packets"] == 0
    assert not (tmp_path / "dead.jsonl").exists()


def test_failed_batch_is_dead_lettered_not_discarded(tmp_path):
    manager = _manager(tmp_path)
    repository = StubPacketRepository(failures=99)
    batch = [packet_row(0), packet_row(1)]

    assert manager._save_packets(batch, repository) is None
    assert repository.calls == 2

    status = manager.status()
    assert status["storage_failed_packets"] == 2
    assert "dead-lettered" in status["error"]

    lines = (tmp_path / "dead.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1

    payload = json.loads(lines[0])
    assert payload["count"] == 2
    assert payload["packets"][0]["source_ip"] == "10.0.0.1"
    assert "simulated database failure" in payload["error"]
    assert manager.dead_letter.records_written == 2


def test_database_writer_drains_queue_into_packets_and_connections(tmp_path):
    manager = _manager(tmp_path, batch_size=10)
    rows = [packet_row(index) for index in range(5)]

    thread = threading.Thread(target=manager._database_writer, daemon=True)
    thread.start()

    for row in rows:
        manager.packet_queue.put_nowait(row)

    manager.packet_queue.join()
    manager._writer_stop_event.set()
    thread.join(timeout=10)

    assert not thread.is_alive()
    assert manager.status()["stored_packets"] == 5

    session = SessionLocal()

    try:
        assert session.query(PacketRecord).count() == 5
        assert session.query(ConnectionRecord).count() == 5
        assert session.query(NetworkStatistics).count() == 0

    finally:
        session.close()


def test_queue_overflow_is_counted_as_dropped(tmp_path, monkeypatch):
    manager = _manager(tmp_path, queue_size=1)
    packet = packet_row(0)

    monkeypatch.setattr(
        manager.packet_processor, "process", lambda *a, **k: packet
    )

    # Fill the queue so the next packet cannot be stored.
    manager.packet_queue.put_nowait(packet)
    manager._process_captured_packet(object())

    status = manager.status()

    assert status["processed_packets"] == 1
    assert status["storage_dropped_packets"] == 1
    assert status["queued_packets"] == 1


def test_unprocessable_packet_is_ignored(tmp_path, monkeypatch):
    manager = _manager(tmp_path)

    monkeypatch.setattr(
        manager.packet_processor, "process", lambda *a, **k: None
    )

    manager._process_captured_packet(object())

    status = manager.status()
    assert status["processed_packets"] == 0
    assert status["queued_packets"] == 0


def test_statistics_snapshot_can_be_persisted(tmp_path):
    manager = _manager(tmp_path)
    session = SessionLocal()

    try:
        repository = StatisticsRepository(session)
        manager._write_statistics_snapshot(repository)

        assert repository.count() == 1
        assert repository.get_latest() is not None

    finally:
        session.close()


def test_status_reports_zeroed_counters_before_start(tmp_path):
    status = _manager(tmp_path).status()

    assert status["running"] is False
    assert status["interface"] == "Test Interface"
    assert status["captured_packets"] == 0
    assert status["processed_packets"] == 0
    assert status["stored_packets"] == 0
    assert status["storage_dropped_packets"] == 0
    assert status["storage_failed_packets"] == 0
    assert status["connection_errors"] == 0
    assert status["dead_letter_records"] == 0
    assert status["capture"] is None
    assert status["statistics"]["total_packets"] == 0
