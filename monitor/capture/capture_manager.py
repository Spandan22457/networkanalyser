"""
Coordinates packet capture, processing, statistics and persistence.

Pipeline::

    Scapy sniff
        -> _process_captured_packet   (capture thread)
        -> PacketProcessor            (metadata only)
        -> StatisticsEngine           (in-memory live counters)
        -> bounded queue
        -> _database_writer           (writer thread)
        -> PacketRepository           (batch insert)
        -> SQLite

Two background threads run beside the capture thread:

* the database writer drains the bounded queue in batches and also folds the
  same batch into connection rows;
* the statistics writer persists one snapshot every ``statistics_interval``
  seconds, plus a final snapshot on shutdown.

The capture callback never performs a database operation, so a slow disk
cannot stall packet capture.  When the queue is full the packet is counted as
``storage_dropped``; when a batch fails twice it is counted as
``storage_failed`` and written to the dead-letter file instead of vanishing.
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Mapping, Sequence
from typing import Any

from monitor.capture.connection_tracker import build_flows
from monitor.capture.packet_capture import PacketCapture
from monitor.processing.packet_processor import PacketProcessor
from monitor.statistics.statistics_engine import StatisticsEngine
from monitor.storage.connection_repository import ConnectionRepository
from monitor.storage.database import SessionLocal
from monitor.storage.dead_letter import DeadLetterWriter
from monitor.storage.packet_repository import PacketRepository
from monitor.storage.statistics_repository import StatisticsRepository


def _empty_baseline() -> dict[str, int]:
    return {
        "total_packets": 0,
        "total_bytes": 0,
        "upload_bytes": 0,
        "download_bytes": 0,
    }


class CaptureManager:
    """Owns one capture session and all of its worker threads."""

    def __init__(
        self,
        interface: str,
        queue_size: int = 5000,
        batch_size: int = 100,
        statistics_interval: float = 10.0,
        dead_letter: DeadLetterWriter | None = None,
    ):
        self.interface = interface
        self.batch_size = max(1, int(batch_size))
        self.statistics_interval = max(1.0, float(statistics_interval))

        self.packet_processor = PacketProcessor()
        self.statistics_engine = StatisticsEngine()

        self.packet_queue: queue.Queue = queue.Queue(
            maxsize=max(1, int(queue_size))
        )
        self.dead_letter = dead_letter or DeadLetterWriter()

        self.capture: PacketCapture | None = None

        self._writer_thread: threading.Thread | None = None
        self._statistics_thread: threading.Thread | None = None

        self._writer_stop_event = threading.Event()
        self._statistics_stop_event = threading.Event()

        # Re-entrant because status() takes it while snapshot() does too.
        self._lock = threading.RLock()

        self._running = False

        self._processed_packets = 0
        self._stored_packets = 0
        self._storage_dropped_packets = 0
        self._storage_failed_packets = 0
        self._connection_errors = 0

        self._error: str | None = None
        self._baseline = _empty_baseline()

    # ------------------------------------------------------------------
    # Capture thread
    # ------------------------------------------------------------------

    def _process_captured_packet(self, raw_packet) -> None:
        """Process one raw packet received from Scapy."""

        try:
            packet_data = self.packet_processor.process(
                raw_packet,
                interface=self.interface,
            )

            if packet_data is None:
                return

            self.statistics_engine.update(packet_data)

            with self._lock:
                self._processed_packets += 1

            try:
                self.packet_queue.put_nowait(packet_data)

            except queue.Full:
                with self._lock:
                    self._storage_dropped_packets += 1

        except Exception as exc:  # pragma: no cover - defensive
            with self._lock:
                self._error = f"Packet processing error: {exc}"

    # ------------------------------------------------------------------
    # Database writer thread
    # ------------------------------------------------------------------

    def _collect_batch(self) -> list[dict[str, Any]]:
        batch: list[dict[str, Any]] = []

        try:
            batch.append(self.packet_queue.get(timeout=0.5))
        except queue.Empty:
            return batch

        while len(batch) < self.batch_size:
            try:
                batch.append(self.packet_queue.get_nowait())
            except queue.Empty:
                break

        return batch

    def _persist_batch(
        self,
        batch: Sequence[dict[str, Any]],
        packets: PacketRepository,
        connections: ConnectionRepository,
    ) -> None:
        saved = self._save_packets(batch, packets)

        if saved is None:
            return

        with self._lock:
            self._stored_packets += saved

        try:
            connections.upsert_flows(build_flows(batch))

        except Exception as exc:
            with self._lock:
                self._connection_errors += 1
                self._error = f"Connection writer error: {exc}"

    def _save_packets(
        self,
        batch: Sequence[dict[str, Any]],
        packets: PacketRepository,
    ) -> int | None:
        """Insert once, retry once, then dead-letter. Returns rows written."""

        try:
            return packets.save_packets(batch)

        except Exception as first_error:
            try:
                return packets.save_packets(batch)

            except Exception as second_error:
                with self._lock:
                    self._storage_failed_packets += len(batch)
                    self._error = (
                        "Database write failed twice, batch dead-lettered: "
                        f"{second_error}"
                    )

                try:
                    self.dead_letter.write(batch, second_error)

                except Exception as dead_letter_error:  # pragma: no cover
                    with self._lock:
                        self._error = (
                            f"{self._error}; dead-letter write failed: "
                            f"{dead_letter_error} "
                            f"(first error was {first_error})"
                        )

                return None

    def _database_writer(self) -> None:
        db = SessionLocal()
        packets = PacketRepository(db)
        connections = ConnectionRepository(db)

        try:
            while (
                not self._writer_stop_event.is_set()
                or not self.packet_queue.empty()
            ):
                batch = self._collect_batch()

                if not batch:
                    continue

                try:
                    self._persist_batch(batch, packets, connections)

                finally:
                    for _ in batch:
                        self.packet_queue.task_done()

        finally:
            db.close()

    # ------------------------------------------------------------------
    # Statistics writer thread
    # ------------------------------------------------------------------

    def _write_statistics_snapshot(self, repository) -> None:
        try:
            repository.add_snapshot(self.snapshot())

        except Exception as exc:
            with self._lock:
                self._error = f"Statistics writer error: {exc}"

    def _statistics_writer(self) -> None:
        db = SessionLocal()
        repository = StatisticsRepository(db)

        try:
            while not self._statistics_stop_event.wait(
                self.statistics_interval
            ):
                self._write_statistics_snapshot(repository)

            # Final snapshot so the last interval is not lost.
            self._write_statistics_snapshot(repository)

        finally:
            db.close()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _reset_counters(self) -> None:
        self._processed_packets = 0
        self._stored_packets = 0
        self._storage_dropped_packets = 0
        self._storage_failed_packets = 0
        self._connection_errors = 0
        self._error = None

        self.statistics_engine.reset()

    def _read_baseline(self) -> dict[str, int]:
        """Totals already stored before this session started."""

        db = SessionLocal()

        try:
            packets = PacketRepository(db)
            totals = packets.get_totals()
            directions = packets.get_direction_totals()

        except Exception:
            return _empty_baseline()

        finally:
            db.close()

        return {
            "total_packets": int(totals["total_packets"]),
            "total_bytes": int(totals["total_bytes"]),
            "upload_bytes": int(
                directions.get("outgoing", {}).get("bytes", 0)
            ),
            "download_bytes": int(
                directions.get("incoming", {}).get("bytes", 0)
            ),
        }

    def start(self) -> bool:
        """Start the writer threads and packet capture."""

        self._writer_stop_event.clear()
        self._statistics_stop_event.clear()

        with self._lock:
            if self._running:
                return False

            if self._writer_thread and self._writer_thread.is_alive():
                return False

            self._reset_counters()
            self._baseline = self._read_baseline()

            self.capture = PacketCapture(
                interface=self.interface,
                packet_callback=self._process_captured_packet,
            )

            self._writer_thread = threading.Thread(
                target=self._database_writer,
                name="NetworkDatabaseWriter",
                daemon=True,
            )
            self._statistics_thread = threading.Thread(
                target=self._statistics_writer,
                name="NetworkStatisticsWriter",
                daemon=True,
            )

            self._writer_thread.start()
            self._statistics_thread.start()

            self._running = True

        started = self.capture.start()

        if not started:
            self.stop()
            return False

        return True

    def stop(self) -> bool:
        """Stop capture, flush the queue, then write a final snapshot."""

        with self._lock:
            capture = self.capture

        if capture is not None and not capture.stop():
            with self._lock:
                self._error = "Packet capture thread did not stop cleanly."
            return False

        # No more packets can enter the queue.
        self._writer_stop_event.set()

        writer = self._writer_thread

        if writer and writer.is_alive():
            writer.join(timeout=30)

        if writer and writer.is_alive():
            with self._lock:
                self._error = "Database writer did not finish flushing."
            return False

        self._statistics_stop_event.set()

        statistics = self._statistics_thread

        if statistics and statistics.is_alive():
            statistics.join(timeout=10)

        with self._lock:
            self._running = False

        return True

    def is_running(self) -> bool:
        return self._running

    # ------------------------------------------------------------------
    # Read-only views
    # ------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """Cumulative session statistics merged onto the pre-session totals."""

        snapshot = self.statistics_engine.snapshot()

        with self._lock:
            baseline = dict(self._baseline)

        snapshot["total_packets"] += baseline["total_packets"]
        snapshot["total_bytes"] += baseline["total_bytes"]
        snapshot["upload_bytes"] += baseline["upload_bytes"]
        snapshot["download_bytes"] += baseline["download_bytes"]

        total_packets = snapshot["total_packets"]
        total_bytes = snapshot["total_bytes"]

        snapshot["average_packet_size"] = (
            round(total_bytes / total_packets, 2)
            if total_packets
            else 0
        )
        snapshot["top_talkers"] = self.statistics_engine.top_talkers(10)

        return snapshot

    def status(self) -> dict[str, Any]:
        """Consistent snapshot of capture, storage and statistics counters."""

        with self._lock:
            capture_status = (
                self.capture.status() if self.capture else None
            )

            return {
                "interface": self.interface,
                "running": self._running,
                "captured_packets": (
                    capture_status["captured_packets"]
                    if capture_status
                    else 0
                ),
                "processed_packets": self._processed_packets,
                "queued_packets": self.packet_queue.qsize(),
                "stored_packets": self._stored_packets,
                "storage_dropped_packets": self._storage_dropped_packets,
                "storage_failed_packets": self._storage_failed_packets,
                "connection_errors": self._connection_errors,
                "dead_letter_records": self.dead_letter.records_written,
                "statistics": self.snapshot(),
                "capture": capture_status,
                "error": self._error,
            }
