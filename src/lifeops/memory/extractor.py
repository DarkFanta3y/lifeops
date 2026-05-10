from __future__ import annotations

from typing import Any


class MemoryExtractor:
    def normalize_preferences(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        return [item for item in payload.get("preferences", []) if isinstance(item, dict)]

    def normalize_entities(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        return [item for item in payload.get("entities", []) if isinstance(item, dict)]

    def normalize_relations(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        return [item for item in payload.get("relations", []) if isinstance(item, dict)]
