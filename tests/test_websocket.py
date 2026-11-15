"""WebSocket behaviour: snapshot shape, multi-client fan-out, safe disconnect."""

from __future__ import annotations

from monitor.storage.packet_repository import PacketRepository
from tests.helpers import packet_row


REQUIRED_KEYS = {
    "type",
    "timestamp",
    "running",
    "interface",
    "captured_packets",
    "processed_packets",
    "stored_packets",
    "queued_packets",
    "total_packets",
    "total_bytes",
    "upload_speed",
    "download_speed",
    "packets_per_second",
    "protocol_counts",
    "top_talkers",
    "source",
}


def test_live_frame_matches_the_contract(client):
    with client.websocket_connect("/ws/live") as socket:
        frame = socket.receive_json()

    assert REQUIRED_KEYS <= set(frame)
    assert frame["type"] == "live"
    assert frame["running"] is False
    assert frame["source"] in {"database", "empty"}


def test_live_frame_reflects_persisted_totals(client, db):
    PacketRepository(db).save_packets(
        [
            packet_row(0, packet_size=100),
            packet_row(1, packet_size=200),
        ]
    )

    with client.websocket_connect("/ws/live") as socket:
        frame = socket.receive_json()

    assert frame["total_packets"] == 2
    assert frame["total_bytes"] == 300
    assert frame["protocol_counts"] == {"UDP": 2}
    assert frame["source"] == "database"


def test_multiple_clients_receive_the_same_snapshot(client, db):
    PacketRepository(db).save_packets([packet_row(0, packet_size=64)])

    with client.websocket_connect("/ws/live") as first:
        with client.websocket_connect("/ws/live") as second:
            first_frame = first.receive_json()
            second_frame = second.receive_json()

    assert first_frame["total_packets"] == 1
    assert second_frame["total_packets"] == 1
    assert first_frame["source"] == second_frame["source"] == "database"


def test_disconnect_does_not_stop_the_session(client):
    with client.websocket_connect("/ws/live") as socket:
        socket.receive_json()

    # Closing the socket must not affect capture ownership or the API.
    assert client.get("/api/capture/status").json()["running"] is False
    assert client.get("/api/health").status_code == 200

    # A new client can connect straight away.
    with client.websocket_connect("/ws/live") as socket:
        assert socket.receive_json()["type"] == "live"
