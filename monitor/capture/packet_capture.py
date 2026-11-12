
import threading
import time
from typing import Callable, Optional

from scapy.all import sniff


class PacketCapture:
    """
    Background packet-capture manager.

    Captures packets from a selected network interface.
    Packet processing is delegated to the supplied callback.
    """

    def __init__(
        self,
        interface: str,
        packet_callback: Optional[Callable] = None,
        capture_filter: Optional[str] = None,
    ):
        self.interface = interface
        self.packet_callback = packet_callback
        self.capture_filter = capture_filter

        self._stop_event = threading.Event()
        self._thread = None
        self._lock = threading.Lock()

        self._running = False
        self._captured_packets = 0
        self._dropped_callback_errors = 0
        self._error = None

    def _process_packet(self, packet):
        try:
            with self._lock:
                self._captured_packets += 1

            if self.packet_callback:
                self.packet_callback(packet)

        except Exception as exc:
            with self._lock:
                self._dropped_callback_errors += 1
                self._error = str(exc)

    def _capture_loop(self):
        try:
            while not self._stop_event.is_set():

                sniff(
                    iface=self.interface,
                    filter=self.capture_filter,
                    prn=self._process_packet,
                    store=False,
                    timeout=1
                )

        except Exception as exc:
            with self._lock:
                self._error = str(exc)

        finally:
            with self._lock:
                self._running = False

    def start(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return False

            self._stop_event.clear()
            self._captured_packets = 0
            self._dropped_callback_errors = 0
            self._error = None
            self._running = True

            self._thread = threading.Thread(
                target=self._capture_loop,
                name="NetworkPacketCapture",
                daemon=True
            )

            self._thread.start()

        return True

    def stop(self):
        self._stop_event.set()

        thread = self._thread

        if thread and thread.is_alive():
            thread.join(timeout=5)

        if thread and thread.is_alive():
            return False

        return True

    def status(self):
        with self._lock:
            return {
                "interface": self.interface,
                "running": self._running,
                "captured_packets": self._captured_packets,
                "callback_errors": self._dropped_callback_errors,
                "error": self._error
            }
