"""Add packet link-layer/interface columns, statistics and connections.

Revision ID: 0002_stage2
Revises: 0001_baseline
Create Date: 2026-11-15

Every step is guarded by an existence check.  The project has several copies
of the database created by ``Base.metadata.create_all`` at different model
versions, so this revision must be safe to run against:

* the original 400k-row ``packets`` table (plain ADD COLUMN, no rewrite);
* a database that already received the columns from ``create_all``;
* an empty database created by ``alembic upgrade head``.

``packets.timestamp`` is intentionally left as ``VARCHAR(40)`` holding
ISO-8601 UTC strings; see ``monitor/storage/models.py`` for the rationale.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002_stage2"
down_revision: Union[str, None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


NEW_PACKET_COLUMNS = (
    ("source_mac", sa.String(length=17)),
    ("destination_mac", sa.String(length=17)),
    ("interface", sa.String(length=255)),
)


def _column_names(inspector, table: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table)}


def _index_names(inspector, table: str) -> set[str]:
    return {index["name"] for index in inspector.get_indexes(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    # -- packets: nullable columns, metadata-only ALTER ----------------
    if "packets" in tables:
        existing_columns = _column_names(inspector, "packets")

        for name, type_ in NEW_PACKET_COLUMNS:
            if name not in existing_columns:
                op.add_column(
                    "packets",
                    sa.Column(name, type_, nullable=True),
                )

        if "ix_packets_interface" not in _index_names(inspector, "packets"):
            op.create_index(
                "ix_packets_interface", "packets", ["interface"]
            )

    # -- network_statistics -------------------------------------------
    if "network_statistics" not in tables:
        op.create_table(
            "network_statistics",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column(
                "timestamp",
                sa.DateTime(timezone=True),
                nullable=False,
            ),
            sa.Column(
                "total_packets", sa.BigInteger(), nullable=False
            ),
            sa.Column("total_bytes", sa.BigInteger(), nullable=False),
            sa.Column("upload_bytes", sa.BigInteger(), nullable=False),
            sa.Column("download_bytes", sa.BigInteger(), nullable=False),
            sa.Column("upload_speed", sa.Float(), nullable=False),
            sa.Column("download_speed", sa.Float(), nullable=False),
            sa.Column(
                "packets_per_second", sa.Float(), nullable=False
            ),
        )
        op.create_index(
            "ix_network_statistics_timestamp",
            "network_statistics",
            ["timestamp"],
        )
        op.create_index(
            "idx_statistics_timestamp_id",
            "network_statistics",
            ["timestamp", "id"],
        )

    # -- connections ---------------------------------------------------
    if "connections" not in tables:
        op.create_table(
            "connections",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("source_ip", sa.String(length=45), nullable=False),
            sa.Column(
                "destination_ip", sa.String(length=45), nullable=False
            ),
            sa.Column("source_port", sa.Integer(), nullable=True),
            sa.Column("destination_port", sa.Integer(), nullable=True),
            sa.Column("protocol", sa.String(length=20), nullable=False),
            sa.Column(
                "first_seen", sa.DateTime(timezone=True), nullable=False
            ),
            sa.Column(
                "last_seen", sa.DateTime(timezone=True), nullable=False
            ),
            sa.Column(
                "packet_count", sa.BigInteger(), nullable=False
            ),
            sa.Column("byte_count", sa.BigInteger(), nullable=False),
            sa.Column(
                "state",
                sa.String(length=20),
                nullable=False,
                server_default="NEW",
            ),
            sa.UniqueConstraint(
                "source_ip",
                "destination_ip",
                "source_port",
                "destination_port",
                "protocol",
                name="uq_connection_flow",
            ),
        )
        op.create_index(
            "ix_connections_source_ip", "connections", ["source_ip"]
        )
        op.create_index(
            "ix_connections_destination_ip",
            "connections",
            ["destination_ip"],
        )
        op.create_index(
            "ix_connections_protocol", "connections", ["protocol"]
        )
        op.create_index(
            "ix_connections_last_seen", "connections", ["last_seen"]
        )
        op.create_index(
            "idx_connection_last_seen_id",
            "connections",
            ["last_seen", "id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "connections" in tables:
        op.drop_table("connections")

    if "network_statistics" in tables:
        op.drop_table("network_statistics")

    if "packets" in tables:
        existing_columns = _column_names(inspector, "packets")

        if "ix_packets_interface" in _index_names(inspector, "packets"):
            op.drop_index("ix_packets_interface", table_name="packets")

        with op.batch_alter_table("packets") as batch:
            for name, _type in NEW_PACKET_COLUMNS:
                if name in existing_columns:
                    batch.drop_column(name)
