
from scapy.packet import Raw


class ProtocolClassifier:
    """
    Identifies application protocols using packet dissection
    and recognizable protocol signatures.

    It does not classify protocols using port numbers alone.
    """

    def classify(self, packet):
        try:
            # Get all dissected Scapy layer names.
            layer_names = {
                layer.__name__
                for layer in packet.layers()
            }

            # DNS: identify an actual DNS layer.
            if "DNS" in layer_names:
                return "DNS"

            # HTTP: identify dissected HTTP layers.
            if "HTTPRequest" in layer_names or "HTTPResponse" in layer_names:
                return "HTTP"

            # TLS: identify Scapy's TLS layers.
            if any(name.startswith("TLS") for name in layer_names):
                return "HTTPS/TLS"

            # Inspect raw bytes for recognizable protocol signatures.
            if Raw in packet:
                payload = bytes(packet[Raw].load)

                if self._is_http(payload):
                    return "HTTP"

                if self._is_tls(payload):
                    return "HTTPS/TLS"

            return "OTHER"

        except Exception as exc:
            print(f"Protocol classification error: {exc}")
            return "OTHER"

    @staticmethod
    def _is_http(payload):
        """Check for recognizable HTTP request or response syntax."""

        if not payload:
            return False

        http_methods = (
            b"GET ",
            b"POST ",
            b"PUT ",
            b"DELETE ",
            b"HEAD ",
            b"OPTIONS ",
            b"PATCH ",
            b"CONNECT ",
            b"TRACE "
        )

        if payload.startswith(http_methods):
            return True

        if (
            payload.startswith(b"HTTP/1.0 ")
            or payload.startswith(b"HTTP/1.1 ")
        ):
            return True

        return False

    @staticmethod
    def _is_tls(payload):
        """
        Check the TLS record header signature.

        TLS record header:
        - Content type: 20–23
        - Record version major byte: 3
        - Record version minor byte: 0–4
        """

        if len(payload) < 5:
            return False

        content_type = payload[0]
        version_major = payload[1]
        version_minor = payload[2]

        return (
            content_type in (20, 21, 22, 23)
            and version_major == 3
            and 0 <= version_minor <= 4
        )
