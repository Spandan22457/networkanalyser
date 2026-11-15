"""
Turn a batch of processed packet dictionaries into connection rows.

Grouping happens per batch (at most ``batch_size`` packets), so memory stays
bounded no matter how long capture runs.  Accumulation across batches is done
by the database upsert.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from monitor.core.timeutils import from_iso


def _state_for(packet: Mapping[str, Any]) -> str:
    protocol = str(packet.get("protocol", "")).upper()

    if protocol != "TCP":
        return "OPEN"

    flags = str(packet.get("tcp_flags") or "")

    if "F" in flags or "R" in flags:
        return "CLOSED"

    return "ESTABLISHED"


def build_flows(
    packets: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Collapse one packet batch into per-5-tuple flow summaries."""

    grouped: dict[tuple, dict[str, Any]] = {}

    for packet in packets:
        key = (
            packet["source_ip"],
            packet["destination_ip"],
            packet.get("source_port"),
            packet.get("destination_port"),
            packet["protocol"],
        )

        timestamp = str(packet["timestamp"])
        size = int(packet["packet_size"])

        flow = grouped.get(key)

        if flow is None:
            grouped[key] = {
                "source_ip": packet["source_ip"],
                "destination_ip": packet["destination_ip"],
                "source_port": packet.get("source_port"),
                "destination_port": packet.get("destination_port"),
                "protocol": packet["protocol"],
                "first_seen": timestamp,
                "last_seen": timestamp,
                "packet_count": 1,
                "byte_count": size,
                "state": _state_for(packet),
            }
            continue

        if timestamp < flow["first_seen"]:
            flow["first_seen"] = timestamp

        if timestamp > flow["last_seen"]:
            flow["last_seen"] = timestamp

        flow["packet_count"] += 1
        flow["byte_count"] += size
        flow["state"] = _state_for(packet)

    return [
        {
            **flow,
            "first_seen": _parse(flow["first_seen"]),
            "last_seen": _parse(flow["last_seen"]),
        }
        for flow in grouped.values()
    ]


def _parse(value: str) -> datetime:
    return from_iso(value)
