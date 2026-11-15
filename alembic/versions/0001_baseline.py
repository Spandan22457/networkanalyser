"""Baseline: the original ``packets`` table.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-11-15

Existing databases that already contain ``packets`` must not run this
revision; stamp it instead::

    alembic stamp 0001_baseline

Fresh databases can simply run ``alembic upgrade head``.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


INDEXES = (
    ("ix_packets_id", ["id"]),
    ("ix_packets_timestamp", ["timestamp"]),
    ("ix_packets_source_ip", ["source_ip"]),
    ("ix_packets_destination_ip", ["destination_ip"]),
    ("ix_packets_protocol", ["protocol"]),
    ("ix_packets_application_protocol", ["application_protocol"]),
    ("ix_packets_direction", ["direction"]),
    ("idx_packet_timestamp_id", ["timestamp", "id"]),
    ("idx_packet_protocol_timestamp", ["protocol", "timestamp"]),
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "packets" in inspector.get_table_names():
        return

    op.create_table(
        "packets",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("timestamp", sa.String(length=40), nullable=False),
        sa.Column("source_ip", sa.String(length=45), nullable=False),
        sa.Column("destination_ip", sa.String(length=45), nullable=False),
        sa.Column("source_port", sa.Integer(), nullable=True),
        sa.Column("destination_port", sa.Integer(), nullable=True),
        sa.Column("protocol", sa.String(length=20), nullable=False),
        sa.Column(
            "application_protocol",
            sa.String(length=30),
            nullable=False,
        ),
        sa.Column("packet_size", sa.Integer(), nullable=False),
        sa.Column("tcp_flags", sa.String(length=30), nullable=True),
        sa.Column("direction", sa.String(length=20), nullable=False),
        sa.Column("ip_version", sa.Integer(), nullable=False),
    )

    for name, columns in INDEXES:
        op.create_index(name, "packets", columns, unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "packets" not in inspector.get_table_names():
        return

    for name, _columns in reversed(INDEXES):
        op.drop_index(name, table_name="packets")

    op.drop_table("packets")
