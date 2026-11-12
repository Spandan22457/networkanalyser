
from scapy.all import IP, TCP, UDP, DNS, DNSQR
from scapy.packet import Raw

from monitor.processing.protocol_classifier import ProtocolClassifier


classifier = ProtocolClassifier()

# Test 1: DNS packet
dns_packet = (
    IP(src="192.168.1.10", dst="8.8.8.8")
    / UDP(sport=53000, dport=53)
    / DNS(rd=1, qd=DNSQR(qname="example.com"))
)

# Test 2: HTTP request
http_packet = (
    IP(src="192.168.1.10", dst="93.184.216.34")
    / TCP(sport=50000, dport=80)
    / Raw(load=b"GET / HTTP/1.1\r\nHost: example.com\r\n\r\n")
)

# Test 3: TLS record header
tls_payload = bytes([
    0x16,  # Handshake record
    0x03,  # TLS major version
    0x03,  # TLS record version
    0x00, 0x04,  # Record length
    0x01, 0x00, 0x00, 0x00
])

tls_packet = (
    IP(src="192.168.1.10", dst="93.184.216.34")
    / TCP(sport=50001, dport=443)
    / Raw(load=tls_payload)
)

# Test 4: Ordinary TCP packet
other_packet = (
    IP(src="192.168.1.10", dst="192.168.1.20")
    / TCP(sport=50002, dport=9000)
    / Raw(load=b"Hello network")
)

tests = [
    ("DNS", dns_packet),
    ("HTTP", http_packet),
    ("HTTPS/TLS", tls_packet),
    ("OTHER", other_packet)
]

for expected, packet in tests:
    actual = classifier.classify(packet)

    print(
        f"Expected: {expected:12} "
        f"Actual: {actual:12} "
        f"{'PASS' if expected == actual else 'FAIL'}"
    )
