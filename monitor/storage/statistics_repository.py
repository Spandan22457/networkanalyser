"""
Repository for periodic statistics snapshots.

Snapshots are written on an interval (Stage 3), not per packet, so the
dashboard can show historical trends without querying the packet table.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from monitor.core.timeutils import utcnow

from .models import NetworkStatistics


class StatisticsRepository:

    def __init__(self, db: Session):
        self.db = db

    def add_snapshot(
        self,
        snapshot: Mapping[str, Any],
        timestamp: datetime | None = None,
    ) -> NetworkStatistics:
        """Persist one statistics snapshot."""

        record = NetworkStatistics(
            timestamp=timestamp or utcnow(),
            total_packets=int(snapshot.get("total_packets", 0)),
            total_bytes=int(snapshot.get("total_bytes", 0)),
            upload_bytes=int(snapshot.get("upload_bytes", 0)),
            download_bytes=int(snapshot.get("download_bytes", 0)),
            upload_speed=float(
                snapshot.get("upload_bytes_per_second", 0.0)
            ),
            download_speed=float(
                snapshot.get("download_bytes_per_second", 0.0)
            ),
            packets_per_second=float(
                snapshot.get("packets_per_second", 0.0)
            ),
        )

        try:
            self.db.add(record)
            self.db.commit()

        except Exception:
            self.db.rollback()
            raise

        return record

    def get_latest(self) -> NetworkStatistics | None:
        """Most recent snapshot, or ``None`` when history is empty."""

        return (
            self.db.execute(
                select(NetworkStatistics)
                .order_by(NetworkStatistics.id.desc())
                .limit(1)
            )
            .scalars()
            .first()
        )

    def get_history(
        self,
        limit: int = 100,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[NetworkStatistics]:
        """Snapshots newest-first, optionally bounded by time."""

        limit = max(1, min(int(limit), 5000))

        query = select(NetworkStatistics)

        if since is not None:
            query = query.where(NetworkStatistics.timestamp >= since)

        if until is not None:
            query = query.where(NetworkStatistics.timestamp <= until)

        return list(
            self.db.execute(
                query.order_by(NetworkStatistics.id.desc()).limit(limit)
            )
            .scalars()
            .all()
        )

    def count(self) -> int:
        """Number of stored snapshots."""

        return int(
            self.db.execute(
                select(func.count(NetworkStatistics.id))
            ).scalar_one()
        )
