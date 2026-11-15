"""
Repository for packet metadata.

Only this module builds queries against ``PacketRecord``; API handlers and
background workers call repository methods.  Every method that writes wraps
the transaction and rolls back on failure.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from .models import PacketRecord


# Substrings accepted by ``search`` and the columns they are matched against.
SEARCH_COLUMNS = (
    PacketRecord.source_ip,
    PacketRecord.destination_ip,
    PacketRecord.protocol,
    PacketRecord.application_protocol,
    PacketRecord.source_mac,
    PacketRecord.destination_mac,
)

SORT_COLUMNS: dict[str, Any] = {
    "id": PacketRecord.id,
    "timestamp": PacketRecord.timestamp,
    "packet_size": PacketRecord.packet_size,
    "protocol": PacketRecord.protocol,
    "source_ip": PacketRecord.source_ip,
    "destination_ip": PacketRecord.destination_ip,
}


class PacketRepository:

    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def save_packets(self, packets: Sequence[Mapping[str, Any]]) -> int:
        """
        Insert a batch of processed packet dictionaries in one transaction.

        Returns the number of rows written.  Raises after rolling back so the
        caller can count the batch as a storage failure.
        """

        if not packets:
            return 0

        records = [
            PacketRecord(
                timestamp=packet["timestamp"],
                source_ip=packet["source_ip"],
                destination_ip=packet["destination_ip"],
                source_mac=packet.get("source_mac"),
                destination_mac=packet.get("destination_mac"),
                source_port=packet.get("source_port"),
                destination_port=packet.get("destination_port"),
                protocol=packet["protocol"],
                application_protocol=packet.get(
                    "application_protocol", "OTHER"
                ),
                packet_size=packet["packet_size"],
                tcp_flags=packet.get("tcp_flags"),
                direction=packet["direction"],
                ip_version=packet["ip_version"],
                interface=packet.get("interface"),
            )
            for packet in packets
        ]

        try:
            self.db.add_all(records)
            self.db.commit()

        except Exception:
            self.db.rollback()
            raise

        return len(records)

    def clear_packets(self) -> int:
        """Delete every stored packet record."""

        try:
            deleted = self.db.query(PacketRecord).delete()
            self.db.commit()
            return int(deleted)

        except Exception:
            self.db.rollback()
            raise

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get_by_id(self, packet_id: int) -> PacketRecord | None:
        """Return one packet by primary key, or ``None``."""

        return self.db.get(PacketRecord, packet_id)

    def build_query(
        self,
        protocol: str | None = None,
        application_protocol: str | None = None,
        direction: str | None = None,
        search: str | None = None,
        interface: str | None = None,
        min_packet_size: int | None = None,
        max_packet_size: int | None = None,
    ) -> Select:
        """Build the filtered SELECT shared by list/count/export."""

        query = select(PacketRecord)

        if protocol:
            query = query.where(
                PacketRecord.protocol == protocol.upper()
            )

        if application_protocol:
            query = query.where(
                PacketRecord.application_protocol
                == application_protocol.upper()
            )

        if direction:
            query = query.where(
                PacketRecord.direction == direction.lower()
            )

        if interface:
            query = query.where(PacketRecord.interface == interface)

        if min_packet_size is not None:
            query = query.where(
                PacketRecord.packet_size >= min_packet_size
            )

        if max_packet_size is not None:
            query = query.where(
                PacketRecord.packet_size <= max_packet_size
            )

        if search:
            term = f"%{search.strip()}%"
            query = query.where(
                or_(*(column.ilike(term) for column in SEARCH_COLUMNS))
            )

        return query

    def get_packets(
        self,
        limit: int = 100,
        offset: int = 0,
        sort_by: str = "id",
        descending: bool = True,
        **filters: Any,
    ) -> tuple[int, list[PacketRecord]]:
        """
        Return ``(total_matching, page_items)``.

        ``total_matching`` is the count *after* filtering, before pagination.
        """

        limit = max(1, min(int(limit), 1000))
        offset = max(0, int(offset))

        query = self.build_query(**filters)

        count_query = select(func.count()).select_from(
            query.order_by(None).subquery()
        )
        total = int(self.db.execute(count_query).scalar_one())

        column = SORT_COLUMNS.get(sort_by, PacketRecord.id)
        order = column.desc() if descending else column.asc()

        # ``id`` is the tiebreaker so pagination is stable.
        rows = (
            self.db.execute(
                query.order_by(order, PacketRecord.id.desc())
                .offset(offset)
                .limit(limit)
            )
            .scalars()
            .all()
        )

        return total, list(rows)

    def get_recent_packets(self, limit: int = 100) -> list[PacketRecord]:
        """Return the newest packet records."""

        limit = max(1, min(int(limit), 1000))

        return list(
            self.db.execute(
                select(PacketRecord)
                .order_by(PacketRecord.id.desc())
                .limit(limit)
            )
            .scalars()
            .all()
        )

    def get_packet_count(self) -> int:
        """Total number of stored packets."""

        return int(
            self.db.execute(
                select(func.count(PacketRecord.id))
            ).scalar_one()
        )

    def get_totals(self) -> dict[str, int | float]:
        """
        Database-wide aggregates.

        Used when no live capture session exists so the dashboard reflects
        persisted history instead of an empty in-memory engine.
        """

        row = self.db.execute(
            select(
                func.count(PacketRecord.id),
                func.coalesce(func.sum(PacketRecord.packet_size), 0),
                func.count(func.distinct(PacketRecord.source_ip)),
                func.count(func.distinct(PacketRecord.destination_ip)),
                func.min(PacketRecord.timestamp),
                func.max(PacketRecord.timestamp),
            )
        ).one()

        total_packets = int(row[0] or 0)
        total_bytes = int(row[1] or 0)

        return {
            "total_packets": total_packets,
            "total_bytes": total_bytes,
            "average_packet_size": (
                round(total_bytes / total_packets, 2)
                if total_packets
                else 0.0
            ),
            "unique_source_ips": int(row[2] or 0),
            "unique_destination_ips": int(row[3] or 0),
            "first_timestamp": row[4],
            "last_timestamp": row[5],
        }

    def get_direction_totals(self) -> dict[str, dict[str, int]]:
        """Per-direction packet and byte totals."""

        rows = self.db.execute(
            select(
                PacketRecord.direction,
                func.count(PacketRecord.id),
                func.coalesce(func.sum(PacketRecord.packet_size), 0),
            ).group_by(PacketRecord.direction)
        ).all()

        return {
            str(direction): {"packets": int(count), "bytes": int(size)}
            for direction, count, size in rows
        }

    def get_protocol_counts(self) -> dict[str, int]:
        """Transport/control protocol distribution from the database."""

        rows = self.db.execute(
            select(PacketRecord.protocol, func.count(PacketRecord.id))
            .group_by(PacketRecord.protocol)
            .order_by(func.count(PacketRecord.id).desc())
        ).all()

        return {str(name): int(count) for name, count in rows}

    def get_application_protocol_counts(self) -> dict[str, int]:
        """Application protocol distribution from the database."""

        rows = self.db.execute(
            select(
                PacketRecord.application_protocol,
                func.count(PacketRecord.id),
            )
            .group_by(PacketRecord.application_protocol)
            .order_by(func.count(PacketRecord.id).desc())
        ).all()

        return {str(name): int(count) for name, count in rows}

    def get_protocol_totals(self) -> list[dict[str, Any]]:
        """Transport protocol packet and byte totals."""

        rows = self.db.execute(
            select(
                PacketRecord.protocol,
                func.count(PacketRecord.id),
                func.coalesce(func.sum(PacketRecord.packet_size), 0),
            )
            .group_by(PacketRecord.protocol)
            .order_by(func.count(PacketRecord.id).desc())
        ).all()

        return [
            {
                "protocol": str(protocol),
                "packets": int(packets),
                "bytes": int(size),
            }
            for protocol, packets, size in rows
        ]

    def get_application_protocol_totals(self) -> list[dict[str, Any]]:
        """Application protocol packet and byte totals."""

        rows = self.db.execute(
            select(
                PacketRecord.application_protocol,
                func.count(PacketRecord.id),
                func.coalesce(func.sum(PacketRecord.packet_size), 0),
            )
            .group_by(PacketRecord.application_protocol)
            .order_by(func.count(PacketRecord.id).desc())
        ).all()

        return [
            {
                "protocol": str(protocol),
                "packets": int(packets),
                "bytes": int(size),
            }
            for protocol, packets, size in rows
        ]

    def get_top_talkers(self, limit: int = 10) -> list[dict[str, Any]]:
        """Hosts ordered by bytes sent (source side)."""

        limit = max(1, min(int(limit), 100))

        rows = self.db.execute(
            select(
                PacketRecord.source_ip,
                func.count(PacketRecord.id),
                func.coalesce(func.sum(PacketRecord.packet_size), 0),
            )
            .group_by(PacketRecord.source_ip)
            .order_by(func.sum(PacketRecord.packet_size).desc())
            .limit(limit)
        ).all()

        return [
            {
                "ip": str(ip),
                "packets": int(packets),
                "bytes": int(size),
            }
            for ip, packets, size in rows
        ]
