
from sqlalchemy.orm import Session

from .models import PacketRecord


class PacketRepository:

    def __init__(self, db: Session):
        self.db = db

    def save_packets(self, packets):
        """
        Save multiple processed packet records in one transaction.

        Returns the number of saved records.
        """

        if not packets:
            return 0

        records = []

        for packet in packets:

            record = PacketRecord(
                timestamp=packet["timestamp"],
                source_ip=packet["source_ip"],
                destination_ip=packet["destination_ip"],
                source_port=packet.get("source_port"),
                destination_port=packet.get("destination_port"),
                protocol=packet["protocol"],
                application_protocol=packet.get(
                    "application_protocol", "OTHER"
                ),
                packet_size=packet["packet_size"],
                tcp_flags=packet.get("tcp_flags"),
                direction=packet["direction"],
                ip_version=packet["ip_version"]
            )

            records.append(record)

        try:
            self.db.add_all(records)
            self.db.commit()

            return len(records)

        except Exception:
            self.db.rollback()
            raise

    def get_recent_packets(self, limit=100):
        """Retrieve the newest packet records."""

        limit = max(1, min(int(limit), 1000))

        return (
            self.db.query(PacketRecord)
            .order_by(PacketRecord.id.desc())
            .limit(limit)
            .all()
        )

    def get_packet_count(self):
        """Return the total number of stored packets."""

        return self.db.query(PacketRecord).count()

    def clear_packets(self):
        """Delete all stored packet records."""

        try:
            deleted = self.db.query(PacketRecord).delete()
            self.db.commit()
            return deleted

        except Exception:
            self.db.rollback()
            raise
