
from scapy.all import IP, TCP, UDP, DNS, DNSQR
from scapy.packet import Raw

from monitor.processing.packet_processor import PacketProcessor


processor = PacketProcessor()

test_packets = [
    (
        "DNS",
        IP(src="192.168.1.10", dst="8.8.8.8")
        / UDP(sport=53000, dport=53)
        / DNS(rd=1, qd=DNSQR(qname="example.com"))
    ),
    (
        "HTTP",
        IP(src="192.168.1.10", dst="93.184.216.34")
        / TCP(sport=50000, dport=80)
        / Raw(load=b"GET / HTTP/1.1\r\nHost: example.com\r\n\r\n")
    ),
    (
        "HTTPS/TLS",
        IP(src="192.168.1.10", dst="93.184.216.34")
        / TCP(sport=50001, dport=443)
        / Raw(load=bytes([
            0x16, 0x03, 0x03, 0x00, 0x04,
            0x01, 0x00, 0x00, 0x00
        ]))
    )
]

for expected, packet in test_packets:

    result = processor.process(packet)

    if result is None:
        print(f"{expected}: FAIL")
        continue

    actual = result["application_protocol"]

    print(
        f"Expected: {expected:12} "
        f"Actual: {actual:12} "
        f"{'PASS' if expected == actual else 'FAIL'}"
    )

    print("Packet metadata:", result)
    print("-" * 70)
