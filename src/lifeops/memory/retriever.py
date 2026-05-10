from __future__ import annotations

from collections import Counter
from math import sqrt
from typing import Any


class MemoryRetriever:
    def __init__(self, store: Any) -> None:
        self.store = store

    def retrieve(self, query: str, top_k: int = 3) -> list[dict[str, Any]]:
        summaries = self.store.list_conversation_summaries()
        scored = [
            (self._score(query, f"{item.get('summary', '')} {' '.join(item.get('topics', []))}"), item)
            for item in summaries
        ]
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [item for score, item in scored[:top_k] if score > 0 or not query.strip()]

    def _score(self, query: str, text: str) -> float:
        q_chars = Counter(query.casefold())
        t_chars = Counter(text.casefold())
        overlap = sum(min(q_chars[ch], t_chars[ch]) for ch in q_chars)
        q_norm = sqrt(sum(count * count for count in q_chars.values())) or 1
        t_norm = sqrt(sum(count * count for count in t_chars.values())) or 1
        return overlap / (q_norm * t_norm)
