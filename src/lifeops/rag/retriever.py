from __future__ import annotations

import logging
import posixpath
import pickle
import re
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote, urlsplit

from lifeops.core.config import RAGConfig
from lifeops.rag.bm25 import BM25ChunkIndex
from lifeops.rag.embeddings import (
    EmbeddingProvider,
    SentenceTransformerEmbeddingProvider,
    resolve_sentence_transformer_model,
)
from lifeops.rag.fusion import aggregate_parent_documents, reciprocal_rank_fusion
from lifeops.rag.types import ChunkMatch, FileSearchResult, KnowledgeChunk, KnowledgeDocument

logger = logging.getLogger(__name__)


class Reranker(Protocol):
    def score(self, query: str, texts: list[str]) -> list[float]: ...


class CrossEncoderReranker:
    _model_cache = {}

    def __init__(self, model_name: str, cache_folder: str | None = None):
        self.model_name = resolve_sentence_transformer_model(model_name, cache_folder)
        self.cache_folder = cache_folder
        self._model = self._model_cache.get((self.model_name, self.cache_folder))

    @property
    def model(self):
        if self._model is None:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(self.model_name, cache_folder=self.cache_folder)
            self._model_cache[(self.model_name, self.cache_folder)] = self._model
        return self._model

    def score(self, query: str, texts: list[str]) -> list[float]:
        predictions = self.model.predict([(query, text) for text in texts])
        return [float(score) for score in predictions]


class RAGRetriever:
    def __init__(
        self,
        config: RAGConfig,
        embedding_provider: EmbeddingProvider | None = None,
        reranker: Reranker | None = None,
    ):
        self.config = config
        self.embedding_provider = embedding_provider or SentenceTransformerEmbeddingProvider(
            config.embedding_model,
            cache_folder=config.model_cache_path,
        )
        self.reranker = reranker or CrossEncoderReranker(
            config.reranker_model,
            cache_folder=config.model_cache_path,
        )

    def warm_up(self) -> None:
        """提前加载 embedding 与 reranker 模型，避免首次检索承担模型加载开销。"""
        embedding_model_name = getattr(self.embedding_provider, "model_name", None)
        if _can_warm_up_model(embedding_model_name):
            embedding_model = getattr(self.embedding_provider, "model", None)
            if embedding_model is None:
                self.embedding_provider.embed_query("warmup")
        else:
            logger.warning("RAG embedding model is not cached locally, skip warmup")

        reranker_model_name = getattr(self.reranker, "model_name", None)
        if _can_warm_up_model(reranker_model_name):
            reranker_model = getattr(self.reranker, "model", None)
            if reranker_model is None:
                self.reranker.score("warmup", ["warmup"])
        else:
            logger.warning("RAG reranker model is not cached locally, skip warmup")

    def retrieve(
        self,
        query: str,
        *,
        domain: str | None = None,
        category: str | None = None,
        path_prefix: str | None = None,
        top_files: int | None = None,
    ) -> list[FileSearchResult]:
        final_top_files = min(top_files or self.config.final_top_files, self.config.final_top_files, 3)
        vector_matches = self._vector_search(
            query,
            domain=domain,
            category=category,
            path_prefix=path_prefix,
        )
        bm25_matches = self._bm25_search(
            query,
            domain=domain,
            category=category,
            path_prefix=path_prefix,
        )
        fused = reciprocal_rank_fusion(
            [vector_matches, bm25_matches],
            rrf_k=self.config.rrf_k,
            top_k=self.config.rrf_top_k,
        )
        ranked = self._rerank(query, fused)
        parent_documents = self._load_parent_documents()
        return aggregate_parent_documents(
            ranked,
            parent_documents=parent_documents,
            top_files=final_top_files,
            max_evidence_chunks=3,
        )

    def format_results(self, results: list[FileSearchResult]) -> str:
        if not results:
            return "知识库未找到相关 Markdown。"

        lines = ["## 知识库检索结果"]
        for index, result in enumerate(results, start=1):
            tags = "、".join(result.tags) if result.tags else "无"
            lines.append(
                f"\n{index}. {result.title}\n"
                f"路径: {result.path}\n"
                f"领域/分类: {result.domain}/{result.category or '未分类'}\n"
                f"标签: {tags}\n"
                f"Reranker 分数: {result.score:.4f}\n"
                "命中片段:"
            )
            for evidence in result.evidence_chunks:
                snippet = _snippet(evidence.chunk.content)
                lines.append(f"- {evidence.chunk.heading_breadcrumb}: {snippet}")
            lines.append("完整正文:")
            lines.append(_rewrite_markdown_image_assets(result.content.strip(), result.path))
        return "\n".join(lines)

    def _rerank(self, query: str, matches: list[ChunkMatch]) -> list[ChunkMatch]:
        if not matches:
            return []
        texts = [_chunk_search_text(match.chunk) for match in matches]
        try:
            scores = self.reranker.score(query, texts)
        except Exception as exc:
            logger.warning("RAG reranker failed, fallback to RRF ranking: %s", exc)
            return matches

        reranked = [
            ChunkMatch(chunk=match.chunk, score=float(score))
            for match, score in zip(matches, scores, strict=False)
        ]
        return sorted(reranked, key=lambda item: item.score, reverse=True)

    def _bm25_search(
        self,
        query: str,
        *,
        domain: str | None,
        category: str | None,
        path_prefix: str | None,
    ) -> list[ChunkMatch]:
        path = Path(self.config.chroma_path) / "bm25_index.pkl"
        if not path.exists():
            return []
        try:
            with path.open("rb") as file:
                index: BM25ChunkIndex = pickle.load(file)
        except Exception as exc:
            logger.warning("RAG BM25 index load failed, fallback to vector only: %s", exc)
            return []
        return index.search(
            query,
            top_k=self.config.bm25_top_k,
            domain=domain,
            category=category,
            path_prefix=path_prefix,
        )

    def _vector_search(
        self,
        query: str,
        *,
        domain: str | None,
        category: str | None,
        path_prefix: str | None,
    ) -> list[ChunkMatch]:
        try:
            import chromadb

            client = chromadb.PersistentClient(path=self.config.chroma_path)
            collection = client.get_collection(self.config.collection)
            response = collection.query(
                query_embeddings=[self.embedding_provider.embed_query(query)],
                n_results=self.config.vector_top_k * 5 if path_prefix else self.config.vector_top_k,
                where=_where_filter(domain, category),
                include=["documents", "metadatas", "distances"],
            )
        except Exception as exc:
            logger.warning("RAG vector search failed, fallback to BM25 only: %s", exc)
            return []

        matches: list[ChunkMatch] = []
        ids = response.get("ids", [[]])[0]
        documents = response.get("documents", [[]])[0]
        metadatas = response.get("metadatas", [[]])[0]
        distances = response.get("distances", [[]])[0]
        for chunk_id, document, metadata, distance in zip(
            ids, documents, metadatas, distances, strict=False
        ):
            chunk = _chunk_from_chroma(chunk_id, document or "", metadata or {})
            if path_prefix and not chunk.path.startswith(path_prefix):
                continue
            score = 1.0 / (1.0 + float(distance or 0.0))
            matches.append(ChunkMatch(chunk=chunk, score=score))
        return matches

    def _load_parent_documents(self) -> dict[str, KnowledgeDocument]:
        path = Path(self.config.chroma_path) / "parent_documents.pkl"
        if not path.exists():
            return {}
        try:
            with path.open("rb") as file:
                parents: dict[str, KnowledgeDocument] = pickle.load(file)
        except Exception as exc:
            logger.warning("RAG parent document index load failed: %s", exc)
            return {}
        return parents


def _where_filter(domain: str | None, category: str | None) -> dict[str, Any] | None:
    filters = []
    if domain:
        filters.append({"domain": domain})
    if category:
        filters.append({"category": category})
    if not filters:
        return None
    if len(filters) == 1:
        return filters[0]
    return {"$and": filters}


def _can_warm_up_model(model_name: Any) -> bool:
    if not isinstance(model_name, str) or not model_name:
        return True
    path = Path(model_name).expanduser()
    if path.exists():
        return True
    return "/" not in model_name and "\\" not in model_name


def _chunk_from_chroma(chunk_id: str, document: str, metadata: dict[str, Any]) -> KnowledgeChunk:
    tags = str(metadata.get("tags") or "")
    return KnowledgeChunk(
        doc_id=str(metadata.get("doc_id") or ""),
        chunk_id=str(metadata.get("chunk_id") or chunk_id),
        path=str(metadata.get("path") or ""),
        title=str(metadata.get("title") or ""),
        domain=str(metadata.get("domain") or "knowledge"),
        category=str(metadata.get("category") or "") or None,
        tags=[tag for tag in tags.split(",") if tag],
        heading_breadcrumb=str(metadata.get("heading_breadcrumb") or ""),
        content=document,
        content_hash=str(metadata.get("content_hash") or ""),
        parent_id=str(metadata.get("parent_id") or metadata.get("doc_id") or ""),
        parent_path=str(metadata.get("parent_path") or metadata.get("path") or ""),
        parent_title=str(metadata.get("parent_title") or metadata.get("title") or ""),
        parent_content_hash=str(metadata.get("parent_content_hash") or ""),
    )


def _chunk_search_text(chunk: KnowledgeChunk) -> str:
    return f"{chunk.title}\n{chunk.heading_breadcrumb}\n{_strip_heading_lines(chunk.content)}"


def _strip_heading_lines(text: str) -> str:
    lines = [line for line in text.splitlines() if not line.lstrip().startswith("#")]
    return "\n".join(lines).strip()


def _snippet(text: str, max_chars: int = 180) -> str:
    compact = " ".join(text.split())
    if len(compact) <= max_chars:
        return compact
    return f"{compact[:max_chars].rstrip()}..."


_MARKDOWN_IMAGE_RE = re.compile(r"(!\[[^\]]*]\()([^)\s]+)([^)]*\))")
_RAG_ASSET_PREFIX = "/api/rag/assets/"


def _rewrite_markdown_image_assets(markdown: str, document_path: str) -> str:
    def replace(match: re.Match[str]) -> str:
        prefix, raw_url, suffix = match.groups()
        local_url = raw_url[1:-1] if raw_url.startswith("<") and raw_url.endswith(">") else raw_url
        rewritten = _rag_asset_url_for_markdown_image(local_url, document_path)
        if rewritten is None:
            return match.group(0)
        return f"{prefix}{rewritten}{suffix}"

    return _MARKDOWN_IMAGE_RE.sub(replace, markdown)


def _rag_asset_url_for_markdown_image(raw_url: str, document_path: str) -> str | None:
    parsed = urlsplit(raw_url)
    if parsed.scheme or parsed.netloc or raw_url.startswith(("/", "#")):
        return None

    normalized = posixpath.normpath(
        posixpath.join(posixpath.dirname(document_path), parsed.path)
    )
    if normalized == "." or normalized.startswith("../") or "/../" in f"/{normalized}/":
        return None

    encoded_path = quote(normalized, safe="/")
    return f"{_RAG_ASSET_PREFIX}{encoded_path}"
