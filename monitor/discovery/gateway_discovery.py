
import ipaddress
import socket

import psutil
from scapy.all import conf


class GatewayDiscovery:

    def discover(self):
        """Discover the default IPv4 gateway and local subnet."""

        try:
            # Scapy returns: interface, source IP, gateway IP.
            interface, source_ip, gateway_ip = conf.route.route(
                "0.0.0.0"
            )

            interface_name = getattr(
                interface, "name", str(interface)
            )

            if not source_ip or source_ip == "0.0.0.0":
                raise RuntimeError("No active IPv4 route found.")

            if not gateway_ip or gateway_ip == "0.0.0.0":
                raise RuntimeError("No default IPv4 gateway found.")

            network = None

            for addresses in psutil.net_if_addrs().values():
                for address in addresses:
                    if (
                        address.family == socket.AF_INET
                        and address.address == source_ip
                        and address.netmask
                    ):
                        network = ipaddress.IPv4Network(
                            f"{source_ip}/{address.netmask}",
                            strict=False
                        )
                        break

                if network:
                    break

            if network is None:
                raise RuntimeError(
                    "Could not determine the local IPv4 subnet."
                )

            return {
                "interface": interface_name,
                "local_ip": source_ip,
                "gateway_ip": gateway_ip,
                "network": str(network)
            }

        except Exception as exc:
            return {
                "error": str(exc)
            }


def get_default_gateway():
    """Convenience function for other project modules."""

    return GatewayDiscovery().discover()
