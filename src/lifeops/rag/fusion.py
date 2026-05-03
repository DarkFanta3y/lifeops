from __future__ import annotations

from lifeops.rag.types import ChunkMatch, FileSearchResult, KnowledgeDocument


def reciprocal_rank_fusion(
    ranked_lists: list[list[ChunkMatch]],
    *,
    rrf_k: int,
    top_k: int | None = None,
) -> list[ChunkMatch]:
    scores: dict[str, float] = {}
    chunks = {}
    for ranked in ranked_lists:
        for rank, match in enumerate(ranked, start=1):
            scores[match.chunk.chunk_id] = scores.get(match.chunk.chunk_id, 0.0) + (
                1.0 / (rrf_k + rank)
            )
            chunks[match.chunk.chunk_id] = match.chunk

    fused = [
        ChunkMatch(chunk=chunks[chunk_id], score=score)
        for chunk_id, score in sorted(scores.items(), key=lambda item: item[1], reverse=True)
    ]
    return fused[:top_k] if top_k is not None else fused


def aggregate_files(
    fused_matches: list[ChunkMatch],
    *,
    top_files: int,
    max_evidence_chunks: int,
) -> list[FileSearchResult]:
    by_path: dict[str, FileSearchResult] = {}
    for match in fused_matches:
        chunk = match.chunk
        existing = by_path.get(chunk.path)
        if existing is None:
            by_path[chunk.path] = FileSearchResult(
                path=chunk.path,
                title=chunk.title,
                domain=chunk.domain,
                category=chunk.category,
                tags=list(chunk.tags),
                score=match.score,
                evidence_chunks=[match],
            )
            continue

        evidence = existing.evidence_chunks
        if len(evidence) < max_evidence_chunks:
            evidence = [*evidence, match]
        by_path[chunk.path] = FileSearchResult(
            path=existing.path,
            title=existing.title,
            domain=existing.domain,
            category=existing.category,
            tags=list(existing.tags),
            score=max(existing.score, match.score),
            evidence_chunks=evidence,
        )

    return sorted(by_path.values(), key=lambda item: item.score, reverse=True)[:top_files]


def aggregate_parent_documents(
    ranked_matches: list[ChunkMatch],
    *,
    parent_documents: dict[str, KnowledgeDocument],
    top_files: int,
    max_evidence_chunks: int,
) -> list[FileSearchResult]:
    by_parent: dict[str, FileSearchResult] = {}
    for match in ranked_matches:
        chunk = match.chunk
        parent_id = chunk.parent_id or chunk.doc_id or chunk.parent_path or chunk.path
        parent = parent_documents.get(parent_id)
        path = parent.path if parent is not None else (chunk.parent_path or chunk.path)
        title = parent.title if parent is not None else (chunk.parent_title or chunk.title)
        domain = parent.domain if parent is not None else chunk.domain
        category = parent.category if parent is not None else chunk.category
        tags = list(parent.tags if parent is not None else chunk.tags)
        content = parent.content if parent is not None else chunk.content

        existing = by_parent.get(parent_id)
        if existing is None:
            by_parent[parent_id] = FileSearchResult(
                path=path,
                title=title,
                domain=domain,
                category=category,
                tags=tags,
                score=match.score,
                content=content,
                evidence_chunks=[match],
            )
            continue

        evidence = existing.evidence_chunks
        if len(evidence) < max_evidence_chunks:
            evidence = [*evidence, match]
        by_parent[parent_id] = FileSearchResult(
            path=existing.path,
            title=existing.title,
            domain=existing.domain,
            category=existing.category,
            tags=list(existing.tags),
            score=max(existing.score, match.score),
            content=existing.content,
            evidence_chunks=evidence,
        )

    return sorted(by_parent.values(), key=lambda item: item.score, reverse=True)[:top_files]
