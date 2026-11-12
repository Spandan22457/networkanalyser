
from datetime import datetime, timezone
import socket

import psutil
from scapy.all import IP, IPv6, TCP, UDP, ICMP

from .protocol_classifier import ProtocolClassifier


class PacketProcessor:

    def __init__(self):
        self.local_ips = self._get_local_ips()
        self.protocol_classifier = ProtocolClassifier()

    def _get_local_ips(self):
        """Collect IPv4 and IPv6 addresses assigned to local interfaces."""

        addresses = set()

        for interface_addresses in psutil.net_if_addrs().values():
            for address in interface_addresses:

                if address.family == socket.AF_INET:
                    ip = address.address

                elif address.family == socket.AF_INET6:
                    ip = address.address.split("%")[0]

                else:
                    continue

                addresses.add(ip)

        return addresses

    def refresh_local_ips(self):
        """Refresh local addresses when network interfaces change."""
        self.local_ips = self._get_local_ips()

    def _get_direction(self, source_ip, destination_ip):

        source_is_local = source_ip in self.local_ips
        destination_is_local = destination_ip in self.local_ips

        if source_is_local and destination_is_local:
            return "local"

        if source_is_local:
            return "outgoing"

        if destination_is_local:
            return "incoming"

        return "other"

    def _get_protocol(self, packet):
        """Identify the transport or control protocol."""

        if TCP in packet:
            return (
                "TCP",
                int(packet[TCP].sport),
                int(packet[TCP].dport),
                str(packet[TCP].flags)
            )

        if UDP in packet:
            return (
                "UDP",
                int(packet[UDP].sport),
                int(packet[UDP].dport),
                None
            )

        if ICMP in packet:
            return ("ICMP", None, None, None)

        for layer in packet.layers():
            if layer.__name__.startswith("ICMPv6"):
                return ("ICMPv6", None, None, None)

        return ("OTHER", None, None, None)

    def process(self, packet):
        """
        Extract packet metadata and classify its application protocol.

        Returns a dictionary or None.
        Packet payload is never stored.
        """

        try:
            # Identify IP version.
            if IP in packet:
                ip_layer = packet[IP]
                ip_version = 4

            elif IPv6 in packet:
                ip_layer = packet[IPv6]
                ip_version = 6

            else:
                return None

            source_ip = ip_layer.src
            destination_ip = ip_layer.dst

            # Extract transport protocol information.
            (
                protocol,
                source_port,
                destination_port,
                tcp_flags
            ) = self._get_protocol(packet)

            # Identify application protocol.
            application_protocol = self.protocol_classifier.classify(
                packet
            )

            # UTC timestamp.
            timestamp = datetime.fromtimestamp(
                float(packet.time),
                tz=timezone.utc
            ).isoformat()

            # Packet direction.
            direction = self._get_direction(
                source_ip,
                destination_ip
            )

            # Return metadata only.
            return {
                "timestamp": timestamp,
                "source_ip": source_ip,
                "destination_ip": destination_ip,
                "source_port": source_port,
                "destination_port": destination_port,
                "protocol": protocol,
                "application_protocol": application_protocol,
                "packet_size": len(packet),
                "tcp_flags": tcp_flags,
                "direction": direction,
                "ip_version": ip_version
            }

        except Exception as exc:
            print(f"Packet processing error: {exc}")
            return None
