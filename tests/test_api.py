"""REST API contract tests against the isolated test database."""

from __future__ import annotations

from datetime import datetime

from monitor.storage.connection_repository import ConnectionRepository
from monitor.storage.packet_repository import PacketRepository
from monitor.storage.statistics_repository import StatisticsRepository
from tests.helpers import connection_row, packet_row, statistics_row


def _seed(db, rows):
    PacketRepository(db).save_packets(rows)


def test_health_reports_connected_database(client):
    response = client.get("/api/health")

    assert response.status_code == 200

    payload = response.json()
    assert payload["status"] == "healthy"
    assert payload["database"] == "connected"
    assert "packets stored" in payload["detail"]


def test_api_root(client):
    payload = client.get("/api").json()

    assert payload["version"] == "2.0.0"
    assert payload["docs"] == "/docs"


def test_packets_empty_database(client):
    response = client.get("/api/packets")

    assert response.status_code == 200
    assert response.json() == {
        "total": 0,
        "limit": 50,
        "offset": 0,
        "items": [],
    }


def test_packets_pagination(client, db):
    _seed(db, [packet_row(index) for index in range(5)])

    payload = client.get(
        "/api/packets", params={"limit": 2, "offset": 2}
    ).json()

    assert payload["total"] == 5
    assert payload["limit"] == 2
    assert payload["offset"] == 2
    assert len(payload["items"]) == 2


def test_packet_payload_contains_metadata_only(client, db):
    _seed(
        db,
        [
            packet_row(
                0,
                source_ip="10.1.2.3",
                destination_ip="10.4.5.6",
                source_port=12345,
                destination_port=443,
                protocol="TCP",
                application_protocol="HTTPS/TLS",
                packet_size=512,
                direction="outgoing",
                interface="Wi-Fi",
            )
        ],
    )

    item = client.get("/api/packets").json()["items"][0]

    assert item["source_ip"] == "10.1.2.3"
    assert item["destination_ip"] == "10.4.5.6"
    assert item["source_mac"] == "aa:bb:cc:dd:ee:01"
    assert item["interface"] == "Wi-Fi"
    assert item["packet_size"] == 512

    assert "payload" not in item
    assert "raw_bytes" not in item


def test_packets_filtering(client, db):
    _seed(
        db,
        [
            packet_row(0, protocol="UDP", direction="outgoing"),
            packet_row(1, protocol="TCP", direction="incoming"),
            packet_row(
                2,
                protocol="TCP",
                direction="incoming",
                source_ip="192.168.7.7",
                interface="Wi-Fi",
            ),
        ],
    )

    assert client.get(
        "/api/packets", params={"protocol": "TCP"}
    ).json()["total"] == 2
    assert client.get(
        "/api/packets", params={"direction": "incoming"}
    ).json()["total"] == 2
    assert client.get(
        "/api/packets", params={"search": "192.168.7.7"}
    ).json()["total"] == 1
    assert client.get(
        "/api/packets", params={"interface": "Wi-Fi"}
    ).json()["total"] == 1
    assert client.get(
        "/api/packets", params={"min_packet_size": 101}
    ).json()["total"] == 2


def test_packets_sorting(client, db):
    _seed(
        db,
        [packet_row(index, packet_size=500 - index) for index in range(3)],
    )

    payload = client.get(
        "/api/packets",
        params={"sort": "packet_size", "order": "asc"},
    ).json()

    sizes = [item["packet_size"] for item in payload["items"]]
    assert sizes == sorted(sizes)


def test_packets_invalid_sort_returns_400(client):
    response = client.get("/api/packets", params={"sort": "payload"})

    assert response.status_code == 400
    assert "Invalid sort field" in response.json()["detail"]


def test_packets_invalid_order_returns_400(client):
    response = client.get("/api/packets", params={"order": "sideways"})

    assert response.status_code == 400


def test_packets_limit_is_validated(client):
    response = client.get("/api/packets", params={"limit": 1000})

    assert response.status_code == 422


def test_packet_detail_and_404(client, db):
    _seed(db, [packet_row(0)])

    packet_id = client.get("/api/packets").json()["items"][0]["id"]

    detail = client.get(f"/api/packets/{packet_id}")
    assert detail.status_code == 200
    assert detail.json()["id"] == packet_id

    missing = client.get("/api/packets/999999")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Packet not found."


def test_current_statistics_from_database(client, db):
    _seed(
        db,
        [
            packet_row(0, direction="outgoing", packet_size=100),
            packet_row(1, direction="incoming", packet_size=300),
        ],
    )

    payload = client.get("/api/statistics/current").json()

    assert payload["source"] == "database"
    assert payload["total_packets"] == 2
    assert payload["total_bytes"] == 400
    assert payload["average_packet_size"] == 200.0
    assert payload["upload_bytes"] == 100
    assert payload["download_bytes"] == 300
    assert payload["direction_counts"] == {
        "outgoing": 1,
        "incoming": 1,
    }


def test_current_statistics_empty_database(client):
    payload = client.get("/api/statistics/current").json()

    assert payload["source"] == "empty"
    assert payload["total_packets"] == 0


def test_legacy_statistics_alias(client, db):
    _seed(db, [packet_row(0)])

    assert client.get("/api/statistics").json()["total_packets"] == 1


def test_statistics_history(client, db):
    session = db

    StatisticsRepository(session).add_snapshot(
        statistics_row(0), timestamp=datetime(2026, 1, 1, 0, 0, 0)
    )
    StatisticsRepository(session).add_snapshot(
        statistics_row(1), timestamp=datetime(2026, 1, 1, 0, 0, 10)
    )

    response = client.get(
        "/api/statistics/history", params={"limit": 10}
    )

    assert response.status_code == 200

    payload = response.json()
    assert len(payload) == 2
    assert payload[0]["total_packets"] == 101
    assert payload[0]["timestamp"].startswith("2026-01-01T00:00:10")


def test_statistics_history_rejects_bad_timestamp(client):
    response = client.get(
        "/api/statistics/history", params={"since": "not-a-date"}
    )

    assert response.status_code == 400
    assert "Invalid since timestamp" in response.json()["detail"]


def test_protocol_statistics(client, db):
    _seed(
        db,
        [
            packet_row(0, protocol="TCP", application_protocol="HTTPS/TLS"),
            packet_row(1, protocol="TCP", application_protocol="HTTPS/TLS"),
            packet_row(2, protocol="UDP", application_protocol="DNS"),
        ],
    )

    payload = client.get("/api/statistics/protocols").json()

    assert payload["total_packets"] == 3

    transport = {
        row["protocol"]: row for row in payload["protocols"]
    }
    assert transport["TCP"]["percentage"] == 66.67
    assert transport["UDP"]["percentage"] == 33.33

    application = {
        row["protocol"]: row for row in payload["application_protocols"]
    }
    assert application["DNS"]["packets"] == 1


def test_top_talkers(client, db):
    _seed(
        db,
        [
            packet_row(0, source_ip="10.0.0.7", packet_size=1000),
            packet_row(1, source_ip="10.0.0.8", packet_size=10),
        ],
    )

    payload = client.get("/api/top-talkers", params={"limit": 5}).json()

    assert payload[0] == {"ip": "10.0.0.7", "packets": 1, "bytes": 1000}
    assert len(payload) == 2


def test_connections_endpoint(client, db):
    ConnectionRepository(db).upsert_flows(
        [
            connection_row(0, protocol="TCP", state="ESTABLISHED"),
            connection_row(1, protocol="UDP", destination_port=53),
        ]
    )

    payload = client.get("/api/connections").json()

    assert payload["total"] == 2
    assert len(payload["items"]) == 2
    assert payload["items"][0]["last_seen"].endswith("Z") or "+00:00" in payload["items"][0]["last_seen"]


def test_connections_filters_and_validation(client, db):
    ConnectionRepository(db).upsert_flows(
        [
            connection_row(0, protocol="TCP", state="ESTABLISHED"),
            connection_row(
                1,
                protocol="UDP",
                state="OPEN",
                destination_port=53,
                source_ip="172.16.0.4",
            ),
        ]
    )

    assert client.get(
        "/api/connections", params={"protocol": "udp"}
    ).json()["total"] == 1
    assert client.get(
        "/api/connections", params={"state": "established"}
    ).json()["total"] == 1
    assert client.get(
        "/api/connections", params={"search": "172.16"}
    ).json()["total"] == 1

    bad_sort = client.get("/api/connections", params={"sort": "security"})
    assert bad_sort.status_code == 400


def test_capture_status_when_stopped(client):
    payload = client.get("/api/capture/status").json()

    assert payload["running"] is False
    assert payload["captured_packets"] == 0
    assert payload["storage_dropped_packets"] == 0


def test_start_capture_rejects_unknown_interface(client):
    response = client.post(
        "/api/capture/start",
        json={"interface": "definitely-not-an-interface"},
    )

    assert response.status_code == 404


def test_interfaces_endpoint(client):
    response = client.get("/api/interfaces")

    assert response.status_code == 200

    payload = response.json()
    assert payload["count"] == len(payload["interfaces"])

    for interface in payload["interfaces"]:
        assert {"name", "capture_name", "ipv4_addresses", "is_up"} <= set(
            interface
        )


def test_gateway_endpoint_is_available_or_reports_503(client):
    response = client.get("/api/gateway")

    assert response.status_code in (200, 503)

    if response.status_code == 200:
        payload = response.json()
        assert "capture_name" in payload
        assert "local_ip" in payload
