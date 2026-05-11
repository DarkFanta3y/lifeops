from __future__ import annotations

from collections import Counter
from math import log, sqrt
from typing import Any


class MemoryRetriever:
    def __init__(self, store: Any, embedding_provider: Any | None = None) -> None:
        self.store = store
        self.embedding_provider = embedding_provider

    def retrieve(self, query: str, top_k: int = 3) -> list[dict[str, Any]]:
        summaries = self.store.list_conversation_summaries()
        if not summaries:
            return []
        documents = [
            f"{item.get('summary', '')} {' '.join(item.get('topics', []))}" for item in summaries
        ]
        bm25_scores = self._bm25_scores(query, documents)
        embedding_scores = self._embedding_scores(query, summaries)
        scored = []
        for index, item in enumerate(summaries):
            score = bm25_scores[index] + embedding_scores[index]
            scored.append((score, item))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        result = [item for score, item in scored[:top_k] if score > 0 or not query.strip()]
        for item in result:
            if hasattr(self.store, "mark_summary_accessed"):
                self.store.mark_summary_accessed(item["conversation_id"])
        return result

    def _bm25_scores(self, query: str, documents: list[str]) -> list[float]:
        query_terms = self._terms(query)
        if not query_terms:
            return [1.0 for _ in documents]
        doc_terms = [self._terms(document) for document in documents]
        avg_len = sum(len(terms) for terms in doc_terms) / (len(doc_terms) or 1)
        doc_freq: Counter[str] = Counter()
        for terms in doc_terms:
            doc_freq.update(set(terms))
        scores: list[float] = []
        for terms in doc_terms:
            term_counts = Counter(terms)
            score = 0.0
            doc_len = len(terms) or 1
            for term in query_terms:
                if term_counts[term] == 0:
                    continue
                idf = log(1 + (len(documents) - doc_freq[term] + 0.5) / (doc_freq[term] + 0.5))
                numerator = term_counts[term] * 2.2
                denominator = term_counts[term] + 1.2 * (0.25 + 0.75 * doc_len / (avg_len or 1))
                score += idf * numerator / denominator
            if score == 0:
                score = self._char_cosine(query, " ".join(terms))
            scores.append(score)
        return scores

    def _embedding_scores(self, query: str, summaries: list[dict[str, Any]]) -> list[float]:
        if self.embedding_provider is None or not query.strip():
            return [0.0 for _ in summaries]
        try:
            query_embedding = self.embedding_provider.embed_query(query)
        except Exception:
            return [0.0 for _ in summaries]
        scores = []
        for item in summaries:
            embedding = item.get("embedding")
            if not embedding:
                scores.append(0.0)
                continue
            scores.append(self._cosine(query_embedding, embedding))
        return scores

    def _terms(self, text: str) -> list[str]:
        normalized = text.casefold()
        terms = [term for term in normalized.split() if term]
        if terms:
            return terms
        return [char for char in normalized if not char.isspace()]

    def _char_cosine(self, query: str, text: str) -> float:
        q_chars = Counter(query.casefold())
        t_chars = Counter(text.casefold())
        overlap = sum(min(q_chars[ch], t_chars[ch]) for ch in q_chars)
        q_norm = sqrt(sum(count * count for count in q_chars.values())) or 1
        t_norm = sqrt(sum(count * count for count in t_chars.values())) or 1
        return overlap / (q_norm * t_norm)

    def _cosine(self, left: list[float], right: list[float]) -> float:
        if not left or not right or len(left) != len(right):
            return 0.0
        dot = sum(a * b for a, b in zip(left, right, strict=True))
        left_norm = sqrt(sum(item * item for item in left)) or 1
        right_norm = sqrt(sum(item * item for item in right)) or 1
        return dot / (left_norm * right_norm)
