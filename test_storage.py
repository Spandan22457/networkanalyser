
from monitor.storage.database import (
    init_database,
    SessionLocal
)

from monitor.storage.packet_repository import PacketRepository


# Initialize database and create tables.
init_database()

# Create a database session.
db = SessionLocal()

try:
    repository = PacketRepository(db)

    # Sample metadata for database testing only.
    test_packets = [
        {
            "timestamp": "2026-11-11T08:30:00+00:00",
            "source_ip": "192.168.1.10",
            "destination_ip": "8.8.8.8",
            "source_port": 53000,
            "destination_port": 53,
            "protocol": "UDP",
            "application_protocol": "DNS",
            "packet_size": 100,
            "tcp_flags": None,
            "direction": "outgoing",
            "ip_version": 4
        },
        {
            "timestamp": "2026-11-11T08:30:01+00:00",
            "source_ip": "8.8.8.8",
            "destination_ip": "192.168.1.10",
            "source_port": 53,
            "destination_port": 53000,
            "protocol": "UDP",
            "application_protocol": "DNS",
            "packet_size": 150,
            "tcp_flags": None,
            "direction": "incoming",
            "ip_version": 4
        }
    ]

    # Save test records.
    saved = repository.save_packets(test_packets)

    print("Saved packets:", saved)

    # Retrieve records.
    packets = repository.get_recent_packets(limit=10)

    print("\nStored packet records:")

    for packet in packets:
        print(
            packet.id,
            packet.source_ip,
            "->",
            packet.destination_ip,
            packet.protocol,
            packet.application_protocol,
            packet.packet_size
        )

    # Verify database count.
    count = repository.get_packet_count()

    print("\nTotal database records:", count)

    assert saved == 2
    assert count >= 2
    assert packets[0].application_protocol == "DNS"

    print("\nAll database tests passed!")

finally:
    db.close()
