from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from lifeops.utils.logging import get_logger

logger = get_logger(__name__)


class ContextLayer(str, Enum):
    L1 = "l1"
    L2 = "l2"
    L3 = "l3"


@dataclass
class ContextEntry:
    key: str
    content: str
    layer: ContextLayer
    token_count: int


class ContextManager:
    def __init__(
        self,
        max_tokens: int = 200000,
        l1_budget_ratio: float = 0.10,
        l2_budget_ratio: float = 0.60,
        l3_budget_ratio: float = 0.20,
        reserve_ratio: float = 0.10,
    ):
        self.max_tokens = max_tokens
        self.l1_budget_ratio = l1_budget_ratio
        self.l2_budget_ratio = l2_budget_ratio
        self.l3_budget_ratio = l3_budget_ratio
        self.reserve_ratio = reserve_ratio
        self._entries: dict[str, ContextEntry] = {}
        self._l1_keys: set[str] = set()
        self._l2_keys: set[str] = set()
        self._l3_keys: set[str] = set()
        self._compression_events: list[dict[str, Any]] = []

    @property
    def used_tokens(self) -> int:
        return sum(e.token_count for e in self._entries.values())

    @property
    def remaining_tokens(self) -> int:
        return self.max_tokens - self.used_tokens

    @property
    def available_tokens(self) -> int:
        return int(self.max_tokens * (1 - self.reserve_ratio)) - self.used_tokens

    def add_content(
        self,
        key: str,
        content: str,
        layer: ContextLayer,
        token_count: int | None = None,
    ) -> int:
        if token_count is None:
            token_count = self._estimate_tokens(content)

        if key in self._entries:
            self.remove_content(key)

        entry = ContextEntry(key=key, content=content, layer=layer, token_count=token_count)
        self._entries[key] = entry

        if layer == ContextLayer.L1:
            self._l1_keys.add(key)
        elif layer == ContextLayer.L2:
            self._l2_keys.add(key)
        elif layer == ContextLayer.L3:
            self._l3_keys.add(key)

        logger.debug(f"Added context '{key}' to {layer.value}: {token_count} tokens")
        return token_count

    def can_add(self, token_count: int) -> bool:
        budget = int(self.max_tokens * (1 - self.reserve_ratio))
        return self.used_tokens + token_count <= budget

    def remove_content(self, key: str) -> bool:
        entry = self._entries.pop(key, None)
        if entry is None:
            return False
        self._l1_keys.discard(key)
        self._l2_keys.discard(key)
        self._l3_keys.discard(key)
        logger.debug(f"Removed context '{key}': {entry.token_count} tokens freed")
        return True

    def get_content(self, key: str) -> str | None:
        entry = self._entries.get(key)
        return entry.content if entry else None

    def compress_l2(self, keep_keys: set[str] | None = None) -> list[tuple[str, int]]:
        if keep_keys is None:
            keep_keys = set()

        removed = []
        keys_to_remove = self._l2_keys - keep_keys

        for key in sorted(keys_to_remove):
            entry = self._entries.get(key)
            if entry:
                removed.append((key, entry.token_count))
                self.remove_content(key)

        logger.info(f"Compressed L2 context: removed {len(removed)} entries")
        return removed

    def compress_l3(self) -> list[tuple[str, int]]:
        removed = []
        for key in list(self._l3_keys):
            entry = self._entries.get(key)
            if entry:
                removed.append((key, entry.token_count))
                self.remove_content(key)

        logger.info(f"Compressed L3 context: removed {len(removed)} entries")
        return removed

    def get_l1_content(self) -> list[ContextEntry]:
        return [self._entries[k] for k in self._l1_keys if k in self._entries]

    def get_l2_content(self) -> list[ContextEntry]:
        return [self._entries[k] for k in self._l2_keys if k in self._entries]

    def get_l3_content(self) -> list[ContextEntry]:
        return [self._entries[k] for k in self._l3_keys if k in self._entries]

    def get_summary(self) -> dict[str, Any]:
        l1_tokens = sum(self._entries[k].token_count for k in self._l1_keys if k in self._entries)
        l2_tokens = sum(self._entries[k].token_count for k in self._l2_keys if k in self._entries)
        l3_tokens = sum(self._entries[k].token_count for k in self._l3_keys if k in self._entries)
        return {
            "total_used": self.used_tokens,
            "remaining": self.remaining_tokens,
            "available": self.available_tokens,
            "l1_tokens": l1_tokens,
            "l2_tokens": l2_tokens,
            "l3_tokens": l3_tokens,
            "l1_entries": len(self._l1_keys),
            "l2_entries": len(self._l2_keys),
            "l3_entries": len(self._l3_keys),
        }

    def get_context_summary(self) -> dict[str, Any]:
        return self.get_summary()

    def suggest_compression(self) -> dict[str, Any]:
        pressure = self.used_tokens / self.max_tokens if self.max_tokens else 0
        if pressure >= 0.95:
            phase = "critical"
        elif pressure >= 0.90:
            phase = "summarize"
        elif pressure >= 0.85:
            phase = "trim"
        elif pressure >= 0.80:
            phase = "offload"
        elif pressure >= 0.70:
            phase = "pressure"
        else:
            phase = "none"
        return {
            "phase": phase,
            "pressure": pressure,
            "used_tokens": self.used_tokens,
            "max_tokens": self.max_tokens,
        }

    def prioritize_by_intent(self, intent: str) -> list[ContextEntry]:
        intent_text = intent.casefold()
        entries = list(self._entries.values())

        def score(entry: ContextEntry) -> tuple[int, int]:
            content = f"{entry.key}\n{entry.content}".casefold()
            matched = sum(1 for term in intent_text.split() if term and term in content)
            layer_priority = {
                ContextLayer.L1: 3,
                ContextLayer.L2: 2,
                ContextLayer.L3: 1,
            }[entry.layer]
            return (matched, layer_priority)

        return sorted(entries, key=score, reverse=True)

    def log_compression_event(
        self,
        phase: str,
        freed_tokens: int,
        reason: str,
        conversation_id: str | None = None,
    ) -> None:
        self._compression_events.append(
            {
                "phase": phase,
                "freed_tokens": freed_tokens,
                "reason": reason,
                "conversation_id": conversation_id,
            }
        )

    def _estimate_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)
