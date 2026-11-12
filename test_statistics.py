
from monitor.statistics.statistics_engine import StatisticsEngine


engine = StatisticsEngine(window_seconds=10)

test_packets = [
    {
        "source_ip": "192.168.1.10",
        "destination_ip": "8.8.8.8",
        "protocol": "UDP",
        "application_protocol": "DNS",
        "packet_size": 100,
        "direction": "outgoing"
    },
    {
        "source_ip": "8.8.8.8",
        "destination_ip": "192.168.1.10",
        "protocol": "UDP",
        "application_protocol": "DNS",
        "packet_size": 150,
        "direction": "incoming"
    },
    {
        "source_ip": "192.168.1.10",
        "destination_ip": "93.184.216.34",
        "protocol": "TCP",
        "application_protocol": "HTTP",
        "packet_size": 500,
        "direction": "outgoing"
    },
    {
        "source_ip": "93.184.216.34",
        "destination_ip": "192.168.1.10",
        "protocol": "TCP",
        "application_protocol": "HTTP",
        "packet_size": 1000,
        "direction": "incoming"
    }
]

for packet in test_packets:
    engine.update(packet)

stats = engine.snapshot()

print("\nNETWORK STATISTICS")
print("-" * 45)

for key, value in stats.items():
    print(f"{key}: {value}")

# Basic correctness checks
assert stats["total_packets"] == 4
assert stats["total_bytes"] == 1750
assert stats["upload_bytes"] == 600
assert stats["download_bytes"] == 1150
assert stats["unique_source_ips"] == 3
assert stats["unique_destination_ips"] == 3
assert stats["protocol_counts"]["TCP"] == 2
assert stats["protocol_counts"]["UDP"] == 2
assert stats["application_protocol_counts"]["DNS"] == 2
assert stats["application_protocol_counts"]["HTTP"] == 2

print("\nAll statistics tests passed!")
