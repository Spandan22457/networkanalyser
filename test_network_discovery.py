
from pprint import pprint

from monitor.discovery.gateway_discovery import GatewayDiscovery
from monitor.discovery.device_discovery import DeviceDiscovery


print("\n1. DEFAULT GATEWAY DISCOVERY")
print("=" * 50)

gateway = GatewayDiscovery().discover()
pprint(gateway)

if "error" in gateway:
    print("\nGateway discovery failed:", gateway["error"])
    raise SystemExit(1)


print("\n2. LOCAL NETWORK DEVICE DISCOVERY")
print("=" * 50)

discovery = DeviceDiscovery(timeout=3, max_hosts=1024)
result = discovery.discover()

pprint(result)

if "error" in result:
    print("\nDevice discovery failed:", result["error"])
    raise SystemExit(1)

print("\nDiscovered devices:", result["device_count"])
print("\nNetwork discovery test completed!")
