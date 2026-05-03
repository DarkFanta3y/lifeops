from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class KnowledgeDocument:
    doc_id: str
    path: str
    title: str
    domain: str
    category: str | None
    tags: list[str]
    source: str | None
    updated_at: str | None
    content: str
    content_hash: str = ""


@dataclass(frozen=True)
class KnowledgeChunk:
    doc_id: str
    chunk_id: str
    path: str
    title: str
    domain: str
    category: str | None
    tags: list[str]
    heading_breadcrumb: str
    content: str
    content_hash: str
    parent_id: str = ""
    parent_path: str = ""
    parent_title: str = ""
    parent_content_hash: str = ""


@dataclass(frozen=True)
class ChunkMatch:
    chunk: KnowledgeChunk
    score: float


@dataclass(frozen=True)
class FileSearchResult:
    path: str
    title: str
    domain: str
    category: str | None
    tags: list[str]
    score: float
    content: str = ""
    evidence_chunks: list[ChunkMatch] = field(default_factory=list)
