"""Synthetic data builders shared by the tests."""

from __future__ import annotations

from datetime import datetime


def packet_row(index: int = 0, **overrides):
    """A synthetic packet dictionary matching PacketProcessor output."""

    row = {
        "timestamp": f"2026-01-01T00:00:{index % 60:02d}+00:00",
        "source_ip": f"10.0.0.{index % 250 + 1}",
        "destination_ip": "8.8.8.8",
        "source_mac": "aa:bb:cc:dd:ee:01",
        "destination_mac": "aa:bb:cc:dd:ee:02",
        "source_port": 40000 + index,
        "destination_port": 53,
        "protocol": "UDP",
        "application_protocol": "DNS",
        "packet_size": 100 + index,
        "tcp_flags": None,
        "direction": "outgoing",
        "ip_version": 4,
        "interface": "Ethernet 1",
    }
    row.update(overrides)
    return row


def connection_row(index: int = 0, **overrides):
    """A synthetic flow dictionary for ConnectionRepository.upsert_flows."""

    first_seen = datetime(2026, 1, 1, 12, 0, index % 60)

    row = {
        "source_ip": f"10.0.0.{index + 1}",
        "destination_ip": "93.184.216.34",
        "source_port": 50000 + index,
        "destination_port": 443,
        "protocol": "TCP",
        "first_seen": first_seen,
        "last_seen": first_seen,
        "packet_count": 1,
        "byte_count": 100,
        "state": "ESTABLISHED",
    }
    row.update(overrides)
    return row


def statistics_row(index: int = 0, **overrides):
    """A synthetic statistics snapshot."""

    row = {
        "total_packets": 100 + index,
        "total_bytes": 10_000 + index,
        "upload_bytes": 4_000 + index,
        "download_bytes": 6_000,
        "upload_bytes_per_second": 12.5,
        "download_bytes_per_second": 7.5,
        "packets_per_second": 3.0,
    }
    row.update(overrides)
    return row
