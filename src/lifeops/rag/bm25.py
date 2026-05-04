from __future__ import annotations

from dataclasses import dataclass

from lifeops.rag.tokenizer import tokenize
from lifeops.rag.types import ChunkMatch, KnowledgeChunk

try:
    from rank_bm25 import BM25Okapi
except Exception:  # pragma: no cover - 依赖缺失时的降级路径
    BM25Okapi = None


@dataclass
class BM25ChunkIndex:
    chunks: list[KnowledgeChunk]
    tokenized_corpus: list[list[str]]
    bm25: object | None = None

    @classmethod
    def from_chunks(cls, chunks: list[KnowledgeChunk]) -> "BM25ChunkIndex":
        tokenized = [tokenize(_chunk_search_text(chunk)) for chunk in chunks]
        bm25 = BM25Okapi(tokenized) if BM25Okapi is not None and tokenized else None
        return cls(chunks=list(chunks), tokenized_corpus=tokenized, bm25=bm25)

    def search(
        self,
        query: str,
        *,
        top_k: int,
        domain: str | None = None,
        category: str | None = None,
        path_prefix: str | None = None,
    ) -> list[ChunkMatch]:
        query_tokens = tokenize(query)
        if not query_tokens:
            return []

        scores = self._scores(query_tokens)
        matches: list[ChunkMatch] = []
        for chunk, score in zip(self.chunks, scores, strict=False):
            if score <= 0:
                continue
            if domain and chunk.domain != domain:
                continue
            if category and chunk.category != category:
                continue
            if path_prefix and not chunk.path.startswith(path_prefix):
                continue
            matches.append(ChunkMatch(chunk=chunk, score=float(score)))

        return sorted(matches, key=lambda item: item.score, reverse=True)[:top_k]

    def _scores(self, query_tokens: list[str]) -> list[float]:
        lexical_scores = [
            float(sum(1 for token in tokens if token in set(query_tokens)))
            for tokens in self.tokenized_corpus
        ]
        if self.bm25 is not None:
            return [
                max(0.0, float(score)) + lexical
                for score, lexical in zip(
                    self.bm25.get_scores(query_tokens), lexical_scores, strict=False
                )
            ]

        return lexical_scores


def _chunk_search_text(chunk: KnowledgeChunk) -> str:
    tags = " ".join(chunk.tags)
    return f"{chunk.title}\n{chunk.heading_breadcrumb}\n{chunk.category or ''}\n{tags}\n{chunk.content}"
