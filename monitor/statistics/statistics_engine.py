
import threading
import time
from collections import Counter, deque


class StatisticsEngine:
    """
    Calculates cumulative and rolling statistics from processed packets.

    Thread-safe: can be updated by the capture thread and read by
    the API/dashboard thread.
    """

    def __init__(self, window_seconds=10):
        self.window_seconds = window_seconds
        self._lock = threading.Lock()

        # Cumulative statistics
        self.total_packets = 0
        self.total_bytes = 0

        self.protocol_counts = Counter()
        self.application_protocol_counts = Counter()
        self.direction_counts = Counter()

        self.upload_bytes = 0
        self.download_bytes = 0

        self.source_ips = set()
        self.destination_ips = set()

        # Per-host traffic for the "top talkers" panel.
        self.source_packets = Counter()
        self.source_bytes = Counter()
        self.destination_bytes = Counter()

        # Rolling records: (monotonic timestamp, packet size, direction)
        self._recent_packets = deque()

    def update(self, packet_data):
        """Update statistics using one processed packet dictionary."""

        if not isinstance(packet_data, dict):
            return False

        try:
            packet_size = int(packet_data["packet_size"])
            protocol = str(packet_data["protocol"])
            application_protocol = str(
                packet_data.get("application_protocol", "OTHER")
            )
            direction = str(packet_data["direction"])

            if packet_size < 0:
                return False

        except (KeyError, TypeError, ValueError):
            return False

        source_ip = packet_data.get("source_ip")
        destination_ip = packet_data.get("destination_ip")

        now = time.monotonic()

        with self._lock:
            self.total_packets += 1
            self.total_bytes += packet_size

            self.protocol_counts[protocol] += 1
            self.application_protocol_counts[
                application_protocol
            ] += 1
            self.direction_counts[direction] += 1

            if direction == "outgoing":
                self.upload_bytes += packet_size

            elif direction == "incoming":
                self.download_bytes += packet_size

            if source_ip:
                self.source_ips.add(source_ip)
                self.source_packets[source_ip] += 1
                self.source_bytes[source_ip] += packet_size

            if destination_ip:
                self.destination_ips.add(destination_ip)
                self.destination_bytes[destination_ip] += packet_size

            self._recent_packets.append(
                (now, packet_size, direction)
            )

            self._remove_expired_packets(now)

        return True

    def _remove_expired_packets(self, now):
        """Remove records outside the rolling statistics window."""

        cutoff = now - self.window_seconds

        while (
            self._recent_packets
            and self._recent_packets[0][0] < cutoff
        ):
            self._recent_packets.popleft()

    def snapshot(self):
        """Return a consistent copy of current statistics."""

        now = time.monotonic()

        with self._lock:
            self._remove_expired_packets(now)

            recent_count = len(self._recent_packets)
            recent_bytes = sum(
                item[1] for item in self._recent_packets
            )

            recent_upload = sum(
                size
                for _, size, direction in self._recent_packets
                if direction == "outgoing"
            )

            recent_download = sum(
                size
                for _, size, direction in self._recent_packets
                if direction == "incoming"
            )

            window = self.window_seconds

            return {
                "total_packets": self.total_packets,
                "total_bytes": self.total_bytes,

                "average_packet_size": (
                    round(self.total_bytes / self.total_packets, 2)
                    if self.total_packets else 0
                ),

                "protocol_counts": dict(self.protocol_counts),
                "application_protocol_counts": dict(
                    self.application_protocol_counts
                ),
                "direction_counts": dict(self.direction_counts),

                "upload_bytes": self.upload_bytes,
                "download_bytes": self.download_bytes,

                "unique_source_ips": len(self.source_ips),
                "unique_destination_ips": len(
                    self.destination_ips
                ),

                "rolling_window_seconds": window,
                "packets_per_second": round(
                    recent_count / window, 2
                ),
                "bytes_per_second": round(
                    recent_bytes / window, 2
                ),
                "upload_bytes_per_second": round(
                    recent_upload / window, 2
                ),
                "download_bytes_per_second": round(
                    recent_download / window, 2
                )
            }

    def reset(self):
        """Reset all cumulative and rolling statistics."""

        with self._lock:
            self.total_packets = 0
            self.total_bytes = 0

            self.protocol_counts.clear()
            self.application_protocol_counts.clear()
            self.direction_counts.clear()

            self.upload_bytes = 0
            self.download_bytes = 0

            self.source_ips.clear()
            self.destination_ips.clear()

            self.source_packets.clear()
            self.source_bytes.clear()
            self.destination_bytes.clear()

            self._recent_packets.clear()

    def top_talkers(self, limit=10):
        """Hosts ordered by bytes sent, from the current session."""

        limit = max(1, min(int(limit), 100))

        with self._lock:
            items = [
                {
                    "ip": ip,
                    "packets": self.source_packets[ip],
                    "bytes": size
                }
                for ip, size in self.source_bytes.most_common(limit)
            ]

        return items

