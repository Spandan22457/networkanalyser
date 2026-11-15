"""ConnectionRepository: atomic upserts, filters, pagination and stale close."""

from __future__ import annotations

from datetime import datetime

from monitor.storage.connection_repository import ConnectionRepository
from tests.helpers import connection_row


def test_upsert_inserts_flow(db):
    repository = ConnectionRepository(db)

    assert repository.upsert_flows([connection_row(0)]) == 1

    total, rows = repository.get_connections(limit=10)

    assert total == 1
    assert rows[0].source_ip == "10.0.0.1"
    assert rows[0].destination_port == 443
    assert rows[0].packet_count == 1


def test_upsert_same_flow_increments_counters(db):
    repository = ConnectionRepository(db)
    first = datetime(2026, 1, 1, 12, 0, 10)
    earlier = datetime(2026, 1, 1, 12, 0, 5)
    later = datetime(2026, 1, 1, 12, 0, 20)

    repository.upsert_flows(
        [
            connection_row(
                0,
                first_seen=first,
                last_seen=first,
                packet_count=1,
                byte_count=100,
            )
        ]
    )
    repository.upsert_flows(
        [
            connection_row(
                0,
                first_seen=earlier,
                last_seen=later,
                packet_count=2,
                byte_count=50,
                state="CLOSED",
            )
        ]
    )

    total, rows = repository.get_connections(limit=10)
    flow = rows[0]

    assert total == 1
    assert flow.packet_count == 3
    assert flow.byte_count == 150
    assert flow.first_seen == earlier
    assert flow.last_seen == later
    assert flow.state == "CLOSED"


def test_distinct_flows_are_separate_rows(db):
    repository = ConnectionRepository(db)

    repository.upsert_flows(
        [
            connection_row(0, destination_port=443),
            connection_row(0, destination_port=80),
        ]
    )

    assert repository.get_connection_count() == 2


def test_portless_protocols_normalise_to_zero(db):
    repository = ConnectionRepository(db)

    repository.upsert_flows(
        [
            connection_row(
                0,
                protocol="ICMP",
                source_port=None,
                destination_port=None,
                packet_count=1,
                byte_count=64,
            )
        ]
    )
    repository.upsert_flows(
        [
            connection_row(
                0,
                protocol="ICMP",
                source_port=None,
                destination_port=None,
                packet_count=1,
                byte_count=64,
            )
        ]
    )

    total, rows = repository.get_connections(limit=10)

    assert total == 1
    assert rows[0].source_port == 0
    assert rows[0].destination_port == 0
    assert rows[0].packet_count == 2


def test_filters_protocol_state_and_search(db):
    repository = ConnectionRepository(db)
    repository.upsert_flows(
        [
            connection_row(0, protocol="TCP", state="ESTABLISHED"),
            connection_row(
                1,
                protocol="UDP",
                state="OPEN",
                source_ip="172.16.0.9",
                destination_ip="9.9.9.9",
                destination_port=53,
            ),
        ]
    )

    assert repository.get_connections(protocol="tcp")[0] == 1
    assert repository.get_connections(state="open")[0] == 1
    assert repository.get_connections(search="172.16.0.9")[0] == 1
    assert repository.get_connections(search="9.9.9.9")[0] == 1
    assert repository.get_connections(search="nothing")[0] == 0


def test_pagination_and_sorting(db):
    repository = ConnectionRepository(db)
    repository.upsert_flows(
        [
            connection_row(
                index,
                byte_count=(index + 1) * 100,
                last_seen=datetime(2026, 1, 1, 12, 0, index),
            )
            for index in range(4)
        ]
    )

    total, page = repository.get_connections(
        limit=2, offset=0, sort_by="byte_count", descending=True
    )

    assert total == 4
    assert [row.byte_count for row in page] == [400, 300]


def test_get_by_id_and_protocol_counts(db):
    repository = ConnectionRepository(db)
    repository.upsert_flows(
        [
            connection_row(0, protocol="TCP"),
            connection_row(1, protocol="TCP", destination_port=80),
            connection_row(2, protocol="UDP", destination_port=53),
        ]
    )

    total, rows = repository.get_connections(limit=10)

    assert repository.get_by_id(rows[0].id) is not None
    assert repository.get_by_id(999_999) is None
    assert repository.get_protocol_counts() == {"TCP": 2, "UDP": 1}


def test_mark_stale_closed_only_touches_old_flows(db):
    repository = ConnectionRepository(db)
    repository.upsert_flows(
        [
            connection_row(0, last_seen=datetime(2026, 1, 1, 12, 0, 0)),
            connection_row(
                1,
                destination_port=80,
                last_seen=datetime(2026, 1, 1, 12, 30, 0),
            ),
        ]
    )

    closed = repository.mark_stale_closed(
        cutoff=datetime(2026, 1, 1, 12, 15, 0)
    )

    assert closed == 1

    _, rows = repository.get_connections(limit=10, sort_by="last_seen")
    states = sorted(row.state for row in rows)

    assert states == ["CLOSED", "ESTABLISHED"]

    # Calling it again changes nothing.
    assert repository.mark_stale_closed(
        cutoff=datetime(2026, 1, 1, 12, 15, 0)
    ) == 0


def test_upsert_empty_is_a_noop(db):
    repository = ConnectionRepository(db)

    assert repository.upsert_flows([]) == 0
    assert repository.get_connection_count() == 0
