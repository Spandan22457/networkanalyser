"""
ORM models.

The ``packets`` table already holds production data, therefore its existing
columns and types are preserved exactly.  New columns are nullable so the
Alembic upgrade can add them in place without rewriting rows.

``timestamp`` on ``packets`` stays an ISO-8601 UTC string on purpose:

* it is lexicographically sortable, so ``ORDER BY timestamp`` is chronological;
* converting 400k+ rows to a DATETIME column would rebuild the table and every
  index with no functional gain;
* the value was written by :class:`~monitor.processing.packet_processor`
  with ``tz=timezone.utc`` and always ends in ``+00:00``.

New tables use ``DateTime(timezone=True)`` as they have no legacy data.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class PacketRecord(Base):
    """Metadata for one captured packet.  Payloads are never stored."""

    __tablename__ = "packets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # ISO-8601 UTC string, e.g. "2026-11-15T07:12:25.783509+00:00".
    timestamp: Mapped[str] = mapped_column(
        String(40), nullable=False, index=True
    )

    source_ip: Mapped[str] = mapped_column(
        String(45), nullable=False, index=True
    )
    destination_ip: Mapped[str] = mapped_column(
        String(45), nullable=False, index=True
    )

    # Added in the Stage 2 migration; nullable for historical rows.
    source_mac: Mapped[str | None] = mapped_column(String(17), nullable=True)
    destination_mac: Mapped[str | None] = mapped_column(
        String(17), nullable=True
    )

    source_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    destination_port: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )

    protocol: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True
    )

    application_protocol: Mapped[str] = mapped_column(
        String(30), nullable=False, default="OTHER", index=True
    )

    packet_size: Mapped[int] = mapped_column(Integer, nullable=False)

    tcp_flags: Mapped[str | None] = mapped_column(String(30), nullable=True)

    direction: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True
    )

    ip_version: Mapped[int] = mapped_column(Integer, nullable=False)

    # Capture interface identifier (Scapy/Npcap name), nullable for old rows.
    interface: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )

    __table_args__ = (
        Index("idx_packet_timestamp_id", "timestamp", "id"),
        Index("idx_packet_protocol_timestamp", "protocol", "timestamp"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"PacketRecord(id={self.id!r}, protocol={self.protocol!r}, "
            f"{self.source_ip!r}->{self.destination_ip!r})"
        )


class NetworkStatistics(Base):
    """Point-in-time statistics snapshot, written periodically."""

    __tablename__ = "network_statistics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    total_packets: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    total_bytes: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )

    upload_bytes: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    download_bytes: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )

    upload_speed: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0
    )
    download_speed: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0
    )
    packets_per_second: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0
    )

    __table_args__ = (
        Index("idx_statistics_timestamp_id", "timestamp", "id"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"NetworkStatistics(id={self.id!r}, "
            f"timestamp={self.timestamp!r}, "
            f"total_packets={self.total_packets!r})"
        )


class ConnectionRecord(Base):
    """
    A tracked flow (5-tuple), updated in place as packets arrive.

    ``source_port``/``destination_port`` are nullable because ICMP has no
    ports; the tracker normalises those to ``0`` so the unique constraint still
    detects duplicates.
    """

    __tablename__ = "connections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    source_ip: Mapped[str] = mapped_column(
        String(45), nullable=False, index=True
    )
    destination_ip: Mapped[str] = mapped_column(
        String(45), nullable=False, index=True
    )

    source_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    destination_port: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )

    protocol: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True
    )

    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    packet_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    byte_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )

    # e.g. NEW, ESTABLISHED, CLOSED
    state: Mapped[str] = mapped_column(
        String(20), nullable=False, default="NEW", server_default="NEW"
    )

    __table_args__ = (
        UniqueConstraint(
            "source_ip",
            "destination_ip",
            "source_port",
            "destination_port",
            "protocol",
            name="uq_connection_flow",
        ),
        Index("idx_connection_last_seen_id", "last_seen", "id"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"ConnectionRecord(id={self.id!r}, protocol={self.protocol!r}, "
            f"{self.source_ip!r}:{self.source_port!r}->"
            f"{self.destination_ip!r}:{self.destination_port!r})"
        )
