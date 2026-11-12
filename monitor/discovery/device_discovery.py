
import ipaddress

from scapy.all import ARP, Ether, srp

from monitor.discovery.gateway_discovery import GatewayDiscovery


class DeviceDiscovery:

    def __init__(self, timeout=3, max_hosts=1024):
        self.timeout = timeout
        self.max_hosts = max_hosts

    def discover(self, interface=None):
        """
        Discover responding devices on the local IPv4 subnet.

        Requires authorized access and may require Administrator
        privileges and a working Npcap installation.
        """

        gateway_info = GatewayDiscovery().discover()

        if "error" in gateway_info:
            return {
                "error": gateway_info["error"],
                "devices": []
            }

        network = ipaddress.IPv4Network(
            gateway_info["network"]
        )

        if network.num_addresses > self.max_hosts:
            return {
                "error": (
                    f"Subnet contains {network.num_addresses} addresses. "
                    f"Scan limit is {self.max_hosts}. "
                    "Increase max_hosts only if you are authorized."
                ),
                "devices": []
            }

        capture_interface = (
            interface or gateway_info["interface"]
        )

        try:
            request = (
                Ether(dst="ff:ff:ff:ff:ff:ff")
                / ARP(pdst=str(network))
            )

            answered, _ = srp(
                request,
                iface=capture_interface,
                timeout=self.timeout,
                verbose=False
            )

            devices = []
            seen = set()

            for _, response in answered:
                ip = response.psrc
                mac = response.hwsrc

                if ip in seen:
                    continue

                seen.add(ip)

                devices.append({
                    "ip_address": ip,
                    "mac_address": mac,
                    "is_gateway": (
                        ip == gateway_info["gateway_ip"]
                    )
                })

            return {
                "network": str(network),
                "interface": capture_interface,
                "gateway_ip": gateway_info["gateway_ip"],
                "device_count": len(devices),
                "devices": devices
            }

        except Exception as exc:
            return {
                "error": str(exc),
                "devices": []
            }
