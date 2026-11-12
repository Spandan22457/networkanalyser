
import threading

from scapy.all import IP, UDP, DNS, DNSQR

from monitor.capture.capture_manager import CaptureManager
from monitor.storage.database import init_database, SessionLocal
from monitor.storage.packet_repository import PacketRepository


# Create database tables.
init_database()

# Create manager using a placeholder interface.
manager = CaptureManager(
    interface="test-interface",
    queue_size=100,
    batch_size=10
)

# Start the database writer separately.
manager._writer_thread = threading.Thread(
    target=manager._database_writer,
    daemon=True
)
manager._writer_thread.start()

# Construct a synthetic DNS packet.
test_packet = (
    IP(src="192.168.1.10", dst="8.8.8.8")
    / UDP(sport=53000, dport=53)
    / DNS(
        rd=1,
        qd=DNSQR(qname="example.com")
    )
)

# Send packet through the capture manager's processing pipeline.
manager._process_captured_packet(test_packet)

# Stop writer and allow it to flush its queue.
manager._writer_stop_event.set()
manager._writer_thread.join(timeout=10)

assert not manager._writer_thread.is_alive()

# Verify statistics.
stats = manager.statistics_engine.snapshot()

print("Processed packets:", manager.status()["processed_packets"])
print("Statistics:", stats)

assert stats["total_packets"] == 1
assert stats["application_protocol_counts"]["DNS"] == 1

# Verify database persistence.
db = SessionLocal()

try:
    repository = PacketRepository(db)
    packets = repository.get_recent_packets(limit=1)

    assert packets
    assert packets[0].application_protocol == "DNS"

    print("\nLatest stored packet:")
    print("Source:", packets[0].source_ip)
    print("Destination:", packets[0].destination_ip)
    print("Protocol:", packets[0].protocol)
    print("Application protocol:", packets[0].application_protocol)

finally:
    db.close()

print("\nCapture manager integration test passed!")
