"""PacketRepository: writes, filters, sorting, pagination and aggregates."""

from __future__ import annotations

from monitor.storage.packet_repository import PacketRepository
from tests.helpers import packet_row


def _seed(db, count: int = 5):
    packets = [packet_row(index) for index in range(count)]
    written = PacketRepository(db).save_packets(packets)
    assert written == count
    return packets


def test_save_packets_persists_metadata(db):
    _seed(db, 3)

    repository = PacketRepository(db)
    total, rows = repository.get_packets(limit=10)

    assert total == 3
    assert len(rows) == 3
    assert all(record.interface == "Ethernet 1" for record in rows)
    assert all(record.source_mac == "aa:bb:cc:dd:ee:01" for record in rows)
    assert all(record.timestamp.endswith("+00:00") for record in rows)


def test_save_packets_empty_batch_is_a_noop(db):
    assert PacketRepository(db).save_packets([]) == 0
    assert PacketRepository(db).get_packet_count() == 0


def test_get_by_id_returns_record_or_none(db):
    _seed(db, 1)

    repository = PacketRepository(db)
    _, rows = repository.get_packets(limit=1)
    record = rows[0]

    assert repository.get_by_id(record.id) is not None
    assert repository.get_by_id(999_999) is None


def test_pagination_reports_filtered_total(db):
    _seed(db, 5)

    repository = PacketRepository(db)
    total, rows = repository.get_packets(limit=2, offset=2)

    assert total == 5
    assert len(rows) == 2


def test_protocol_filter_is_case_insensitive(db):
    repository = PacketRepository(db)
    repository.save_packets(
        [
            packet_row(0, protocol="UDP"),
            packet_row(1, protocol="TCP", destination_port=443),
            packet_row(2, protocol="TCP", destination_port=443),
        ]
    )

    total, rows = repository.get_packets(protocol="tcp")

    assert total == 2
    assert {row.protocol for row in rows} == {"TCP"}


def test_application_protocol_filter(db):
    repository = PacketRepository(db)
    repository.save_packets(
        [
            packet_row(0, application_protocol="DNS"),
            packet_row(1, application_protocol="HTTPS/TLS"),
        ]
    )

    total, rows = repository.get_packets(application_protocol="https/tls")

    assert total == 1
    assert rows[0].application_protocol == "HTTPS/TLS"


def test_direction_and_interface_filters(db):
    repository = PacketRepository(db)
    repository.save_packets(
        [
            packet_row(0, direction="outgoing", interface="Ethernet 1"),
            packet_row(1, direction="incoming", interface="Wi-Fi"),
            packet_row(2, direction="incoming", interface="Wi-Fi"),
        ]
    )

    assert repository.get_packets(direction="INCOMING")[0] == 2
    assert repository.get_packets(interface="Wi-Fi")[0] == 2
    assert repository.get_packets(interface="Missing")[0] == 0


def test_search_matches_ip_protocol_and_mac(db):
    repository = PacketRepository(db)
    repository.save_packets(
        [
            packet_row(0, source_ip="10.0.0.5"),
            packet_row(
                1,
                source_ip="192.168.1.9",
                destination_ip="1.1.1.1",
                source_mac="de:ad:be:ef:00:01",
            ),
        ]
    )

    assert repository.get_packets(search="10.0.0.5")[0] == 1
    assert repository.get_packets(search="de:ad:be")[0] == 1
    assert repository.get_packets(search="nope-not-there")[0] == 0


def test_packet_size_bounds(db):
    repository = PacketRepository(db)
    repository.save_packets(
        [packet_row(index, packet_size=100 + index) for index in range(5)]
    )

    assert repository.get_packets(min_packet_size=103)[0] == 2
    assert repository.get_packets(max_packet_size=101)[0] == 2
    assert repository.get_packets(
        min_packet_size=101, max_packet_size=103
    )[0] == 3


def test_sorting_ascending_and_descending(db):
    repository = PacketRepository(db)
    repository.save_packets(
        [packet_row(index, packet_size=200 - index) for index in range(5)]
    )

    _, ascending = repository.get_packets(
        sort_by="packet_size", descending=False, limit=5
    )
    _, descending = repository.get_packets(
        sort_by="packet_size", descending=True, limit=5
    )

    sizes = [row.packet_size for row in ascending]
    assert sizes == sorted(sizes)
    assert [row.packet_size for row in descending] == sorted(
        sizes, reverse=True
    )


def test_unknown_sort_field_falls_back_to_id(db):
    _seed(db, 3)

    total, rows = PacketRepository(db).get_packets(
        sort_by="not_a_column", descending=True
    )

    assert total == 3
    assert [row.id for row in rows] == sorted(
        (row.id for row in rows), reverse=True
    )


def test_totals_and_unique_counts(db):
    repository = PacketRepository(db)
    repository.save_packets(
        [
            packet_row(0, packet_size=100),
            packet_row(1, packet_size=200),
            packet_row(2, source_ip="10.0.0.1", packet_size=300),
        ]
    )

    totals = repository.get_totals()

    assert totals["total_packets"] == 3
    assert totals["total_bytes"] == 600
    assert totals["average_packet_size"] == 200.0
    assert totals["unique_source_ips"] == 2
    assert totals["unique_destination_ips"] == 1


def test_direction_totals(db):
    repository = PacketRepository(db)
    repository.save_packets(
        [
            packet_row(0, direction="outgoing", packet_size=100),
            packet_row(1, direction="incoming", packet_size=50),
            packet_row(2, direction="incoming", packet_size=25),
        ]
    )

    directions = repository.get_direction_totals()

    assert directions["outgoing"] == {"packets": 1, "bytes": 100}
    assert directions["incoming"] == {"packets": 2, "bytes": 75}


def test_protocol_counts_and_totals(db):
    repository = PacketRepository(db)
    repository.save_packets(
        [
            packet_row(0, protocol="UDP", packet_size=100),
            packet_row(1, protocol="TCP", packet_size=200),
            packet_row(2, protocol="TCP", packet_size=300),
        ]
    )

    assert repository.get_protocol_counts() == {"TCP": 2, "UDP": 1}

    totals = {
        row["protocol"]: row for row in repository.get_protocol_totals()
    }

    assert totals["TCP"] == {"protocol": "TCP", "packets": 2, "bytes": 500}
    assert totals["UDP"] == {"protocol": "UDP", "packets": 1, "bytes": 100}


def test_application_protocol_totals(db):
    repository = PacketRepository(db)
    repository.save_packets(
        [
            packet_row(0, application_protocol="DNS"),
            packet_row(1, application_protocol="DNS"),
            packet_row(2, application_protocol="HTTP"),
        ]
    )

    rows = repository.get_application_protocol_totals()

    assert rows[0]["protocol"] == "DNS"
    assert rows[0]["packets"] == 2
    assert {row["protocol"] for row in rows} == {"DNS", "HTTP"}


def test_top_talkers_order_by_bytes_sent(db):
    repository = PacketRepository(db)
    repository.save_packets(
        [
            packet_row(0, source_ip="10.0.0.1", packet_size=900),
            packet_row(1, source_ip="10.0.0.2", packet_size=100),
            packet_row(2, source_ip="10.0.0.2", packet_size=100),
        ]
    )

    talkers = repository.get_top_talkers(limit=2)

    assert talkers[0] == {"ip": "10.0.0.1", "packets": 1, "bytes": 900}
    assert talkers[1] == {"ip": "10.0.0.2", "packets": 2, "bytes": 200}


def test_get_recent_packets_newest_first(db):
    _seed(db, 4)

    recent = PacketRepository(db).get_recent_packets(limit=2)

    assert len(recent) == 2
    assert recent[0].id > recent[1].id


def test_clear_packets_removes_every_row(db):
    _seed(db, 3)

    repository = PacketRepository(db)
    assert repository.clear_packets() == 3
    assert repository.get_packet_count() == 0
