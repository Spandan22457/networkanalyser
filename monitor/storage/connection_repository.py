"""
Repository for tracked connections (flows).

Uses SQLite's ``INSERT ... ON CONFLICT DO UPDATE`` so a batch of flows is
written in one statement and counters are incremented atomically, instead of
select-then-update per packet.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from .models import ConnectionRecord


FLOW_KEY = (
    "source_ip",
    "destination_ip",
    "source_port",
    "destination_port",
    "protocol",
)

SORT_COLUMNS: dict[str, Any] = {
    "id": ConnectionRecord.id,
    "first_seen": ConnectionRecord.first_seen,
    "last_seen": ConnectionRecord.last_seen,
    "packet_count": ConnectionRecord.packet_count,
    "byte_count": ConnectionRecord.byte_count,
}


def _normalise_port(port: Any) -> int:
    """Portless protocols (ICMP) use 0 so the unique key still works."""

    if port is None:
        return 0

    return int(port)


class ConnectionRepository:

    def __init__(self, db: Session):
        self.db = db

    def upsert_flows(
        self, flows: Iterable[Mapping[str, Any]]
    ) -> int:
        """
        Insert new flows and add counters to existing ones.

        Each flow mapping must contain ``source_ip``, ``destination_ip``,
        ``source_port``, ``destination_port``, ``protocol``, ``first_seen``,
        ``last_seen``, ``packet_count``, ``byte_count`` and ``state``.

        Returns the number of flow rows provided.
        """

        rows = []

        for flow in flows:
            rows.append(
                {
                    "source_ip": flow["source_ip"],
                    "destination_ip": flow["destination_ip"],
                    "source_port": _normalise_port(flow.get("source_port")),
                    "destination_port": _normalise_port(
                        flow.get("destination_port")
                    ),
                    "protocol": flow["protocol"],
                    "first_seen": flow["first_seen"],
                    "last_seen": flow["last_seen"],
                    "packet_count": int(flow.get("packet_count", 1)),
                    "byte_count": int(flow.get("byte_count", 0)),
                    "state": flow.get("state", "NEW"),
                }
            )

        if not rows:
            return 0

        statement = sqlite_insert(ConnectionRecord).values(rows)

        statement = statement.on_conflict_do_update(
            index_elements=list(FLOW_KEY),
            set_={
                "first_seen": func.min(
                    ConnectionRecord.first_seen,
                    statement.excluded.first_seen,
                ),
                "last_seen": func.max(
                    ConnectionRecord.last_seen,
                    statement.excluded.last_seen,
                ),
                "packet_count": (
                    ConnectionRecord.packet_count
                    + statement.excluded.packet_count
                ),
                "byte_count": (
                    ConnectionRecord.byte_count
                    + statement.excluded.byte_count
                ),
                "state": statement.excluded.state,
            },
        )

        try:
            self.db.execute(statement)
            self.db.commit()

        except Exception:
            self.db.rollback()
            raise

        return len(rows)

    def get_connections(
        self,
        limit: int = 100,
        offset: int = 0,
        protocol: str | None = None,
        state: str | None = None,
        search: str | None = None,
        sort_by: str = "last_seen",
        descending: bool = True,
    ) -> tuple[int, list[ConnectionRecord]]:
        """Return ``(total_matching, page_items)``."""

        limit = max(1, min(int(limit), 1000))
        offset = max(0, int(offset))

        query = select(ConnectionRecord)

        if protocol:
            query = query.where(
                ConnectionRecord.protocol == protocol.upper()
            )

        if state:
            query = query.where(
                ConnectionRecord.state == state.upper()
            )

        if search:
            term = f"%{search.strip()}%"
            query = query.where(
                or_(
                    ConnectionRecord.source_ip.ilike(term),
                    ConnectionRecord.destination_ip.ilike(term),
                )
            )

        count_query = select(func.count()).select_from(
            query.order_by(None).subquery()
        )
        total = int(self.db.execute(count_query).scalar_one())

        column = SORT_COLUMNS.get(sort_by, ConnectionRecord.last_seen)
        order = column.desc() if descending else column.asc()

        rows = (
            self.db.execute(
                query.order_by(order, ConnectionRecord.id.desc())
                .offset(offset)
                .limit(limit)
            )
            .scalars()
            .all()
        )

        return total, list(rows)

    def get_by_id(self, connection_id: int) -> ConnectionRecord | None:
        """Return one connection by primary key."""

        return self.db.get(ConnectionRecord, connection_id)

    def get_connection_count(self) -> int:
        """Total number of tracked connections."""

        return int(
            self.db.execute(
                select(func.count(ConnectionRecord.id))
            ).scalar_one()
        )

    def get_protocol_counts(self) -> dict[str, int]:
        """Connection count per protocol."""

        rows = self.db.execute(
            select(
                ConnectionRecord.protocol,
                func.count(ConnectionRecord.id),
            )
            .group_by(ConnectionRecord.protocol)
            .order_by(func.count(ConnectionRecord.id).desc())
        ).all()

        return {str(name): int(count) for name, count in rows}

    def mark_stale_closed(
        self, cutoff: datetime, state: str = "CLOSED"
    ) -> int:
        """Mark flows idle since ``cutoff`` as closed."""

        rows = self.db.execute(
            select(ConnectionRecord).where(
                ConnectionRecord.last_seen < cutoff,
                ConnectionRecord.state != state,
            )
        ).scalars().all()

        if not rows:
            return 0

        for record in rows:
            record.state = state

        try:
            self.db.commit()

        except Exception:
            self.db.rollback()
            raise

        return len(rows)
