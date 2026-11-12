
from monitor.discovery.interface_discovery import InterfaceDiscovery


discovery = InterfaceDiscovery()

interfaces = discovery.discover()

print("\nDISCOVERED NETWORK INTERFACES")
print("=" * 70)

for index, interface in enumerate(interfaces, start=1):

    print(f"\nInterface {index}")
    print("-" * 50)

    print("Name:", interface["name"])
    print("Description:", interface["description"])
    print("Capture identifier:", interface["capture_name"])
    print("MAC address:", interface["mac_address"])
    print("IPv4 addresses:", interface["ipv4_addresses"])
    print("IPv6 addresses:", interface["ipv6_addresses"])
    print("Interface active:", interface["is_up"])
    print("Loopback:", interface["is_loopback"])

print("\nACTIVE INTERFACES")
print("=" * 70)

for interface in discovery.get_active_interfaces():
    print(
        interface["name"],
        "|",
        interface["capture_name"]
    )

# Basic checks
assert isinstance(interfaces, list)

for interface in interfaces:
    assert "capture_name" in interface
    assert "ipv4_addresses" in interface
    assert "ipv6_addresses" in interface

print("\nInterface discovery test completed!")
