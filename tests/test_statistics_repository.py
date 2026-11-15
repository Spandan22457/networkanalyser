"""StatisticsRepository: snapshot writes, latest lookup and history queries."""

from __future__ import annotations

from datetime import datetime, timedelta

from monitor.storage.statistics_repository import StatisticsRepository
from tests.helpers import statistics_row


def test_add_snapshot_maps_all_fields(db):
    repository = StatisticsRepository(db)

    record = repository.add_snapshot(
        statistics_row(
            0,
            upload_bytes=111,
            download_bytes=222,
            upload_bytes_per_second=1.5,
            download_bytes_per_second=2.5,
            packets_per_second=3.5,
        )
    )

    assert record.id is not None
    assert record.total_packets == 100
    assert record.total_bytes == 10_000
    assert record.upload_bytes == 111
    assert record.download_bytes == 222
    assert record.upload_speed == 1.5
    assert record.download_speed == 2.5
    assert record.packets_per_second == 3.5


def test_get_latest_returns_none_then_newest(db):
    repository = StatisticsRepository(db)

    assert repository.get_latest() is None

    repository.add_snapshot(statistics_row(0, total_packets=10))
    repository.add_snapshot(statistics_row(1, total_packets=20))

    latest = repository.get_latest()

    assert latest is not None
    assert latest.total_packets == 20


def test_history_is_newest_first_and_limited(db):
    repository = StatisticsRepository(db)

    for index in range(5):
        repository.add_snapshot(
            statistics_row(index),
            timestamp=datetime(2026, 1, 1, 0, 0, index),
        )

    history = repository.get_history(limit=3)

    assert len(history) == 3
    assert [row.total_packets for row in history] == [104, 103, 102]


def test_history_since_and_until_bounds(db):
    repository = StatisticsRepository(db)
    start = datetime(2026, 1, 1, 0, 0, 0)

    for index in range(5):
        repository.add_snapshot(
            statistics_row(index),
            timestamp=start + timedelta(minutes=index),
        )

    window = repository.get_history(
        since=start + timedelta(minutes=1),
        until=start + timedelta(minutes=3),
    )

    assert [row.total_packets for row in window] == [103, 102, 101]


def test_history_limit_is_clamped(db):
    repository = StatisticsRepository(db)
    repository.add_snapshot(statistics_row())

    # A nonsensical limit must still produce a valid query, not an error.
    assert len(repository.get_history(limit=0)) == 1
    assert len(repository.get_history(limit=100_000)) == 1


def test_count_tracks_inserted_snapshots(db):
    repository = StatisticsRepository(db)

    assert repository.count() == 0

    repository.add_snapshot(statistics_row())
    repository.add_snapshot(statistics_row())

    assert repository.count() == 2
