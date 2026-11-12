
import socket

import psutil
from scapy.all import conf


class InterfaceDiscovery:

    def __init__(self):
        self.interfaces = []

    def discover(self):
        """
        Discover network interfaces using Scapy and psutil.

        Scapy supplies capture-compatible interface identifiers.
        psutil supplies IP addresses and operational status.
        """

        discovered = []

        system_addresses = psutil.net_if_addrs()
        system_stats = psutil.net_if_stats()

        for interface in conf.ifaces.values():

            name = getattr(interface, "name", None)

            if not name:
                continue

            description = (
                getattr(interface, "description", None)
                or name
            )

            mac_address = getattr(interface, "mac", None)

            ipv4_addresses = []
            ipv6_addresses = []

            # Match the Scapy interface name to the OS interface name.
            addresses = system_addresses.get(name, [])

            for address in addresses:

                if address.family == socket.AF_INET:
                    ipv4_addresses.append(address.address)

                elif address.family == socket.AF_INET6:
                    ipv6_addresses.append(
                        address.address.split("%")[0]
                    )

                elif getattr(psutil, "AF_LINK", None) == address.family:
                    if not mac_address:
                        mac_address = address.address

            # Get operational status when a matching OS interface exists.
            stats = system_stats.get(name)
            is_up = stats.isup if stats else None

            is_loopback = (
                "loopback" in name.lower()
                or "loopback" in description.lower()
            )

            discovered.append({
                "name": name,
                "description": description,
                "capture_name": name,
                "mac_address": mac_address,
                "ipv4_addresses": ipv4_addresses,
                "ipv6_addresses": ipv6_addresses,
                "is_up": is_up,
                "is_loopback": is_loopback
            })

        self.interfaces = discovered

        return discovered

    def get_interface(self, capture_name):
        """Find an interface using its Scapy capture identifier."""

        for interface in self.interfaces:
            if interface["capture_name"] == capture_name:
                return interface

        return None

    def get_active_interfaces(self):
        """Return interfaces whose operational status is up."""

        return [
            interface
            for interface in self.interfaces
            if interface["is_up"] is True
        ]
