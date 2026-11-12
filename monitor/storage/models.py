
from sqlalchemy import (
    Column,
    Integer,
    String,
    Index
)

from .database import Base


class PacketRecord(Base):

    __tablename__ = "packets"

    id = Column(Integer, primary_key=True, index=True)

    timestamp = Column(String(40), nullable=False, index=True)

    source_ip = Column(String(45), nullable=False, index=True)
    destination_ip = Column(String(45), nullable=False, index=True)

    source_port = Column(Integer, nullable=True)
    destination_port = Column(Integer, nullable=True)

    protocol = Column(String(20), nullable=False, index=True)

    application_protocol = Column(
        String(30),
        nullable=False,
        default="OTHER",
        index=True
    )

    packet_size = Column(Integer, nullable=False)

    tcp_flags = Column(String(30), nullable=True)

    direction = Column(String(20), nullable=False, index=True)

    ip_version = Column(Integer, nullable=False)

    __table_args__ = (
        Index("idx_packet_timestamp_id", "timestamp", "id"),
        Index("idx_packet_protocol_timestamp", "protocol", "timestamp"),
    )
