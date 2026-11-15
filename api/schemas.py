"""
Pydantic response/request schemas.

Single source of truth for what the API returns.  Handlers build responses
through these models, so an accidental field rename fails loudly instead of
silently breaking the dashboard.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator

from monitor.core.timeutils import as_utc


def _serialise_utc(value: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes; always expose them as UTC."""

    return None if value is None else as_utc(value)


# ----------------------------------------------------------------------
# Requests
# ----------------------------------------------------------------------


class StartCaptureRequest(BaseModel):
    interface: str = Field(min_length=1)


# ----------------------------------------------------------------------
# Packets
# ----------------------------------------------------------------------


class PacketOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    timestamp: str
    source_ip: str
    destination_ip: str
    source_mac: str | None = None
    destination_mac: str | None = None
    source_port: int | None = None
    destination_port: int | None = None
    protocol: str
    application_protocol: str
    packet_size: int
    tcp_flags: str | None = None
    direction: str
    ip_version: int
    interface: str | None = None


class PacketPage(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[PacketOut]


# ----------------------------------------------------------------------
# Statistics
# ----------------------------------------------------------------------


class StatisticsSnapshot(BaseModel):
    """Shape of the live (in-memory) statistics engine snapshot."""

    total_packets: int = 0
    total_bytes: int = 0
    average_packet_size: float = 0.0

    protocol_counts: dict[str, int] = Field(default_factory=dict)
    application_protocol_counts: dict[str, int] = Field(default_factory=dict)
    direction_counts: dict[str, int] = Field(default_factory=dict)

    upload_bytes: int = 0
    download_bytes: int = 0

    unique_source_ips: int = 0
    unique_destination_ips: int = 0

    rolling_window_seconds: int = 10
    packets_per_second: float = 0.0
    bytes_per_second: float = 0.0
    upload_bytes_per_second: float = 0.0
    download_bytes_per_second: float = 0.0


class StatisticsResponse(StatisticsSnapshot):
    """
    Snapshot plus provenance.

    ``source`` is ``live`` while a capture session exists, ``database`` when
    totals are derived from stored packets, and ``empty`` on a fresh install.
    """

    source: str = "empty"


class NetworkStatisticsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    timestamp: datetime
    total_packets: int
    total_bytes: int
    upload_bytes: int
    download_bytes: int
    upload_speed: float
    download_speed: float
    packets_per_second: float

    @field_validator("timestamp", mode="after")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return as_utc(value)


class ProtocolStat(BaseModel):
    protocol: str
    packets: int
    bytes: int
    percentage: float


class ProtocolStatistics(BaseModel):
    total_packets: int
    protocols: list[ProtocolStat]
    application_protocols: list[ProtocolStat]


class TopTalker(BaseModel):
    ip: str
    packets: int
    bytes: int


# ----------------------------------------------------------------------
# Connections
# ----------------------------------------------------------------------


class ConnectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_ip: str
    destination_ip: str
    source_port: int | None = None
    destination_port: int | None = None
    protocol: str
    first_seen: datetime
    last_seen: datetime
    packet_count: int
    byte_count: int
    state: str

    @field_validator("first_seen", "last_seen", mode="after")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return as_utc(value)


class ConnectionPage(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[ConnectionOut]


# ----------------------------------------------------------------------
# Capture / health
# ----------------------------------------------------------------------


class StorageCounters(BaseModel):
    captured_packets: int = 0
    processed_packets: int = 0
    queued_packets: int = 0
    stored_packets: int = 0
    storage_dropped_packets: int = 0
    storage_failed_packets: int = 0


class CaptureStatusOut(StorageCounters):
    interface: str | None = None
    running: bool = False
    statistics: StatisticsSnapshot | None = None
    error: str | None = None


class HealthOut(BaseModel):
    status: str
    database: str
    detail: str | None = None


# ----------------------------------------------------------------------
# Errors
# ----------------------------------------------------------------------


class ErrorResponse(BaseModel):
    detail: str
