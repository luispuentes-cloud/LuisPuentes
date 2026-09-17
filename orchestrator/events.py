from __future__ import annotations

from typing import Any

from .state import ControlStore


class EventLedger:
    def __init__(self, store: ControlStore) -> None:
        self.store = store

    def record(
        self,
        event_type: str,
        *,
        entity_type: str | None = None,
        entity_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> str:
        return self.store.append_event(event_type, entity_type, entity_id, payload)

    def list_recent(self, limit: int = 200) -> list[dict[str, Any]]:
        return self.store.list_events(limit=limit)

    def metric(self, name: str, value: float, labels: dict[str, Any] | None = None) -> str:
        return self.store.record_metric(name, value, labels)

    def metrics(self, name: str | None = None) -> list[dict[str, Any]]:
        return self.store.list_metrics(name=name)
