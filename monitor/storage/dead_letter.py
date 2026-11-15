"""
Dead-letter sink for packet batches the database rejected twice.

A record that cannot be persisted is never silently discarded: the batch is
appended to a JSONL file so it can be inspected or replayed later.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from monitor.core.config import settings
from monitor.core.timeutils import utcnow


class DeadLetterWriter:
    """Append-only, thread-safe JSONL writer for failed batches."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else (
            settings.project_root / "storage_failures.jsonl"
        )
        self._lock = threading.Lock()
        self.records_written = 0

    def write(
        self, packets: Sequence[dict[str, Any]], error: Exception | str
    ) -> None:
        payload = {
            "timestamp": utcnow().isoformat(),
            "error": str(error),
            "count": len(packets),
            "packets": list(packets),
        }

        line = json.dumps(payload, ensure_ascii=False, default=str)

        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)

            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")

            self.records_written += len(packets)
