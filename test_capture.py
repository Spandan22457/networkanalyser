
import time

from scapy.all import IP, IPv6, TCP, UDP, ICMP
from monitor.capture.packet_capture import PacketCapture


def display_packet(packet):

    if IP in packet:
        source = packet[IP].src
        destination = packet[IP].dst

    elif IPv6 in packet:
        source = packet[IPv6].src
        destination = packet[IPv6].dst

    else:
        return

    if TCP in packet:
        protocol = "TCP"
    elif UDP in packet:
        protocol = "UDP"
    elif ICMP in packet:
        protocol = "ICMP"
    else:
        protocol = "OTHER"

    print(
        f"{protocol:6} | "
        f"{source:40} -> {destination:40} | "
        f"Size: {len(packet)} bytes"
    )


# Replace this with an actual interface name
INTERFACE = None

if INTERFACE is None:
    from scapy.all import conf
    INTERFACE = conf.iface

capture = PacketCapture(
    interface=INTERFACE,
    packet_callback=display_packet
)

print("Starting packet capture...")
print("Interface:", INTERFACE)

capture.start()

try:
    time.sleep(15)

finally:
    print("\nStopping capture...")
    capture.stop()

print("\nFinal status:")
print(capture.status())
