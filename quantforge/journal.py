"""Append-only JSONL audit trail for every decision, order and risk rejection."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SENSITIVE = ("key", "secret", "token", "password", "authorization")


def redact(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {k: ("***" if any(s in k.lower() for s in SENSITIVE) else redact(v)) for k, v in payload.items()}
    if isinstance(payload, list):
        return [redact(v) for v in payload]
    return payload


class Journal:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else None
        self.events: list[dict[str, Any]] = []
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event_type: str, **payload: Any) -> dict[str, Any]:
        event = {
            "id": uuid.uuid4().hex[:12],
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "type": event_type,
            **redact(payload),
        }
        self.events.append(event)
        if self.path:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, ensure_ascii=False) + "\n")
        return event

    def read(self, limit: int = 100, event_type: str | None = None) -> list[dict[str, Any]]:
        rows = self.events
        if event_type:
            rows = [e for e in rows if e.get("type") == event_type]
        return rows[-limit:]
