"""
UTC datetime helpers.

SQLite does not store timezone offsets, so values are always written as UTC
and re-tagged on the way out.
"""

from __future__ import annotations

from datetime import datetime, timezone


def utcnow() -> datetime:
    """Current time as a timezone-aware UTC datetime."""

    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    """Return ``value`` as an aware UTC datetime (naive values are UTC)."""

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc)


def from_iso(value: str) -> datetime:
    """Parse an ISO-8601 timestamp, defaulting to UTC."""

    return as_utc(datetime.fromisoformat(value))
