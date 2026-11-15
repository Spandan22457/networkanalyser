"""
Statistics read model.

The dashboard must never show zeros just because no capture session is
running.  While a session is live the manager's in-memory counters are used;
otherwise totals are derived from the database.  Database aggregates are
cached briefly so a 1 Hz WebSocket fan-out cannot turn into a full table scan
every second.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Any

from monitor.storage.database import SessionLocal
from monitor.storage.packet_repository import PacketRepository
from monitor.storage.statistics_repository import StatisticsRepository


def _with_percentages(
    rows: list[dict[str, Any]], total: int
) -> list[dict[str, Any]]:
    return [
        {
            **row,
            "percentage": (
                round(row["packets"] / total * 100, 2) if total else 0.0
            ),
        }
        for row in rows
    ]


class StatisticsService:
    """Combines live session counters with persisted history."""

    def __init__(self, session_factory=SessionLocal, cache_ttl: float = 3.0):
        self._session_factory = session_factory
        self._cache_ttl = max(0.0, float(cache_ttl))
        self._lock = threading.Lock()
        self._cached: dict[str, Any] | None = None
        self._cached_at = 0.0

    # ------------------------------------------------------------------
    # Current statistics
    # ------------------------------------------------------------------

    def clear_cache(self) -> None:
        """Drop the cached database snapshot (used after test data changes)."""

        with self._lock:
            self._cached = None
            self._cached_at = 0.0

    def current(self, manager=None) -> dict[str, Any]:
        """Live snapshot when capturing, database totals otherwise."""

        if manager is not None and manager.is_running():
            snapshot = manager.snapshot()
            snapshot["source"] = "live"
            return snapshot

        return self._database_snapshot()

    def _database_snapshot(self) -> dict[str, Any]:
        now = time.monotonic()

        with self._lock:
            if (
                self._cached is not None
                and now - self._cached_at < self._cache_ttl
            ):
                return dict(self._cached)

        snapshot = self._load_database_snapshot()

        with self._lock:
            self._cached = snapshot
            self._cached_at = now

        return dict(snapshot)

    def _load_database_snapshot(self) -> dict[str, Any]:
        db = self._session_factory()

        try:
            packets = PacketRepository(db)
            totals = packets.get_totals()
            directions = packets.get_direction_totals()
            protocol_counts = packets.get_protocol_counts()
            application_counts = (
                packets.get_application_protocol_counts()
            )
            top_talkers = packets.get_top_talkers(10)

        finally:
            db.close()

        total_packets = int(totals["total_packets"])
        total_bytes = int(totals["total_bytes"])

        return {
            "total_packets": total_packets,
            "total_bytes": total_bytes,
            "average_packet_size": (
                round(total_bytes / total_packets, 2)
                if total_packets
                else 0
            ),
            "protocol_counts": protocol_counts,
            "application_protocol_counts": application_counts,
            "direction_counts": {
                direction: values["packets"]
                for direction, values in directions.items()
            },
            "upload_bytes": int(
                directions.get("outgoing", {}).get("bytes", 0)
            ),
            "download_bytes": int(
                directions.get("incoming", {}).get("bytes", 0)
            ),
            "unique_source_ips": int(totals["unique_source_ips"]),
            "unique_destination_ips": int(
                totals["unique_destination_ips"]
            ),
            "rolling_window_seconds": 0,
            "packets_per_second": 0.0,
            "bytes_per_second": 0.0,
            "upload_bytes_per_second": 0.0,
            "download_bytes_per_second": 0.0,
            "top_talkers": top_talkers,
            "source": "database" if total_packets else "empty",
        }

    # ------------------------------------------------------------------
    # Protocol distribution
    # ------------------------------------------------------------------

    def protocols(self) -> dict[str, Any]:
        db = self._session_factory()

        try:
            packets = PacketRepository(db)
            total = packets.get_packet_count()
            transport = packets.get_protocol_totals()
            application = packets.get_application_protocol_totals()

        finally:
            db.close()

        return {
            "total_packets": total,
            "protocols": _with_percentages(transport, total),
            "application_protocols": _with_percentages(application, total),
        }

    # ------------------------------------------------------------------
    # History and top talkers
    # ------------------------------------------------------------------

    def history(
        self,
        limit: int = 100,
        since: datetime | None = None,
        until: datetime | None = None,
    ):
        db = self._session_factory()

        try:
            return StatisticsRepository(db).get_history(
                limit=limit, since=since, until=until
            )

        finally:
            db.close()

    def top_talkers(self, limit: int = 10) -> list[dict[str, Any]]:
        db = self._session_factory()

        try:
            return PacketRepository(db).get_top_talkers(limit)

        finally:
            db.close()


statistics_service = StatisticsService()
