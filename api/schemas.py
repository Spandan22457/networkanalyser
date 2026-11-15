"""
Pydantic request/response schemas.

Single source of truth for the API contract.  Handlers build responses
through these models, so a renamed field fails validation instead of silently
breaking the dashboard.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from monitor.core.timeutils import as_utc


def _utc(value: datetime) -> datetime:
    """Normalise a stored datetime to aware UTC.

    SQLite hands back naive values; PostgreSQL returns aware ones.  Either way
    the API must emit a UTC instant with an offset.
    """

    return as_utc(value)


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


class TopTalker(BaseModel):
    ip: str
    packets: int
    bytes: int


class StatisticsSnapshot(BaseModel):
    """Shape of the live statistics engine snapshot."""

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

    top_talkers: list[TopTalker] = Field(default_factory=list)


class StatisticsResponse(StatisticsSnapshot):
    """
    Snapshot plus provenance.

    ``source`` is ``live`` while a capture session runs, ``database`` when
    totals come from persisted packets, and ``empty`` on a fresh install.
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
    def _as_utc(cls, value: datetime) -> datetime:
        return _utc(value)


class ProtocolStat(BaseModel):
    protocol: str
    packets: int
    bytes: int
    percentage: float


class ProtocolStatistics(BaseModel):
    total_packets: int
    protocols: list[ProtocolStat]
    application_protocols: list[ProtocolStat]


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
    def _as_utc(cls, value: datetime) -> datetime:
        return _utc(value)


class ConnectionPage(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[ConnectionOut]


# ----------------------------------------------------------------------
# Capture / health
# ----------------------------------------------------------------------


class CaptureStatusOut(BaseModel):
    interface: str | None = None
    running: bool = False

    captured_packets: int = 0
    processed_packets: int = 0
    queued_packets: int = 0
    stored_packets: int = 0
    storage_dropped_packets: int = 0
    storage_failed_packets: int = 0
    connection_errors: int = 0
    dead_letter_records: int = 0

    statistics: StatisticsSnapshot | None = None
    capture: dict | None = None
    error: str | None = None


class HealthOut(BaseModel):
    status: str
    database: str
    detail: str | None = None
    # "sqlite" or a server backend such as "postgresql".
    backend: str = "sqlite"


class LiveUpdate(BaseModel):
    """One WebSocket frame pushed to every connected dashboard."""

    type: str = "live"
    timestamp: datetime
    running: bool = False
    interface: str | None = None

    captured_packets: int = 0
    processed_packets: int = 0
    stored_packets: int = 0
    queued_packets: int = 0
    storage_dropped_packets: int = 0
    storage_failed_packets: int = 0

    total_packets: int = 0
    total_bytes: int = 0
    average_packet_size: float = 0.0
    upload_bytes: int = 0
    download_bytes: int = 0
    upload_speed: float = 0.0
    download_speed: float = 0.0
    upload_bytes_per_second: float = 0.0
    download_bytes_per_second: float = 0.0
    bytes_per_second: float = 0.0
    packets_per_second: float = 0.0

    protocol_counts: dict[str, int] = Field(default_factory=dict)
    application_protocol_counts: dict[str, int] = Field(default_factory=dict)
    direction_counts: dict[str, int] = Field(default_factory=dict)
    unique_source_ips: int = 0
    unique_destination_ips: int = 0
    top_talkers: list[TopTalker] = Field(default_factory=list)

    source: str = "empty"
    error: str | None = None


# ----------------------------------------------------------------------
# Errors
# ----------------------------------------------------------------------


class ErrorResponse(BaseModel):
    detail: str
