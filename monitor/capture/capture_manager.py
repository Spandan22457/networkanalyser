
import queue
import threading
from datetime import datetime, timezone

from monitor.capture.packet_capture import PacketCapture
from monitor.processing.packet_processor import PacketProcessor
from monitor.statistics.statistics_engine import StatisticsEngine
from monitor.storage.database import SessionLocal
from monitor.storage.packet_repository import PacketRepository


class CaptureManager:
    """
    Coordinates packet capture, processing, statistics and persistence.

    Packet capture and database writing run on separate threads.
    A bounded queue limits memory usage during traffic bursts.
    """

    def __init__(
        self,
        interface,
        queue_size=5000,
        batch_size=100
    ):
        self.interface = interface
        self.batch_size = batch_size

        self.packet_processor = PacketProcessor()
        self.statistics_engine = StatisticsEngine()

        self.packet_queue = queue.Queue(maxsize=queue_size)

        self.capture = None

        self._writer_thread = None
        self._writer_stop_event = threading.Event()
        self._lock = threading.Lock()

        self._running = False
        self._processed_packets = 0
        self._storage_dropped_packets = 0
        self._storage_failed_packets = 0
        self._error = None

    def _process_captured_packet(self, raw_packet):
        """Process one raw packet received from Scapy."""

        try:
            packet_data = self.packet_processor.process(raw_packet)

            if packet_data is None:
                return

            # Update live statistics immediately.
            self.statistics_engine.update(packet_data)

            with self._lock:
                self._processed_packets += 1

            # Queue packet metadata for asynchronous database storage.
            try:
                self.packet_queue.put_nowait(packet_data)

            except queue.Full:
                with self._lock:
                    self._storage_dropped_packets += 1

        except Exception as exc:
            with self._lock:
                self._error = f"Packet processing error: {exc}"

    def _database_writer(self):
        """Write packet metadata to SQLite in batches."""

        db = SessionLocal()
        repository = PacketRepository(db)

        try:
            while (
                not self._writer_stop_event.is_set()
                or not self.packet_queue.empty()
            ):
                batch = []

                try:
                    first_packet = self.packet_queue.get(timeout=0.5)
                    batch.append(first_packet)

                except queue.Empty:
                    continue

                # Collect more packets without blocking.
                while len(batch) < self.batch_size:
                    try:
                        batch.append(self.packet_queue.get_nowait())
                    except queue.Empty:
                        break

                try:
                    repository.save_packets(batch)

                except Exception as exc:
                    with self._lock:
                        self._storage_failed_packets += len(batch)
                        self._error = f"Database writer error: {exc}"

                finally:
                    for _ in batch:
                        self.packet_queue.task_done()

        finally:
            db.close()

    def start(self):
        """Start the database writer and packet capture."""

        with self._lock:
            if self._running:
                return False

            if self._writer_thread and self._writer_thread.is_alive():
                return False

            self._writer_stop_event.clear()

            self._processed_packets = 0
            self._storage_dropped_packets = 0
            self._storage_failed_packets = 0
            self._error = None

            self.statistics_engine.reset()

            self.capture = PacketCapture(
                interface=self.interface,
                packet_callback=self._process_captured_packet
            )

            self._writer_thread = threading.Thread(
                target=self._database_writer,
                name="NetworkDatabaseWriter",
                daemon=True
            )

            self._writer_thread.start()

            self._running = True

        started = self.capture.start()

        if not started:
            self.stop()
            return False

        return True

    def stop(self):
        """Stop capture first, then flush queued database records."""

        capture_stopped = True

        if self.capture:
            capture_stopped = self.capture.stop()

        if not capture_stopped:
            with self._lock:
                self._error = "Packet capture thread did not stop cleanly."
            return False

        # No more packets should enter the queue now.
        self._writer_stop_event.set()

        writer = self._writer_thread

        if writer and writer.is_alive():
            writer.join(timeout=30)

        if writer and writer.is_alive():
            with self._lock:
                self._error = "Database writer did not finish flushing."
            return False

        with self._lock:
            self._running = False

        return True

    def status(self):
        """Return a snapshot of capture and storage status."""

        with self._lock:
            capture_status = (
                self.capture.status()
                if self.capture else None
            )

            return {
                "interface": self.interface,
                "running": self._running,
                "processed_packets": self._processed_packets,
                "queued_packets": self.packet_queue.qsize(),
                "storage_dropped_packets": (
                    self._storage_dropped_packets
                ),
                "storage_failed_packets": (
                    self._storage_failed_packets
                ),
                "statistics": self.statistics_engine.snapshot(),
                "capture": capture_status,
                "error": self._error
            }
