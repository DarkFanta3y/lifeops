from __future__ import annotations

import json
import pickle
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from lifeops.core.config import RAGConfig
from lifeops.rag.bm25 import BM25ChunkIndex
from lifeops.rag.embeddings import EmbeddingProvider, SentenceTransformerEmbeddingProvider
from lifeops.rag.loader import load_markdown_documents
from lifeops.rag.splitter import split_markdown
from lifeops.rag.types import KnowledgeChunk, KnowledgeDocument, RAGSourceConfig


class RAGIndexer:
    def __init__(
        self,
        config: RAGConfig,
        embedding_provider: EmbeddingProvider | None = None,
        source_configs: list[RAGSourceConfig] | None = None,
    ):
        self.config = config
        self.embedding_provider = embedding_provider or SentenceTransformerEmbeddingProvider(
            config.embedding_model,
            cache_folder=config.model_cache_path,
        )
        self.source_configs = source_configs or []

    def rebuild(self) -> dict[str, int]:
        chroma_path = Path(self.config.chroma_path)
        if chroma_path.exists():
            shutil.rmtree(chroma_path)
        chroma_path.mkdir(parents=True, exist_ok=True)

        documents = load_markdown_documents(self._data_dirs())
        chunks = self._split_documents(documents)

        self._write_parent_documents(documents)
        self._write_chunks_index(chunks)
        self._write_bm25(chunks)
        self._write_chroma(chunks)
        self._write_index_state(len(documents), len(chunks))
        return {"documents": len(documents), "chunks": len(chunks)}

    def sync(self) -> dict[str, int | str]:
        if self._missing_required_indexes():
            summary = self.rebuild()
            return {**summary, "mode": "rebuild"}

        documents = load_markdown_documents(self._data_dirs())
        old_parents = self._load_parent_documents()
        old_chunks = self._load_chunks_index()
        current_documents = {document.doc_id: document for document in documents}

        new_or_updated = [
            document
            for document in documents
            if document.doc_id not in old_parents
            or old_parents[document.doc_id].content_hash != document.content_hash
        ]
        deleted_doc_ids = sorted(set(old_parents) - set(current_documents))
        changed_doc_ids = {document.doc_id for document in new_or_updated}
        affected_doc_ids = changed_doc_ids | set(deleted_doc_ids)

        if not affected_doc_ids:
            if not self._index_state_path().exists():
                self._write_index_state(len(documents), len(old_chunks))
            return {
                "mode": "sync",
                "documents": len(documents),
                "chunks": len(old_chunks),
                "new_documents": 0,
                "updated_documents": 0,
                "deleted_documents": 0,
                "unchanged_documents": len(documents),
            }

        if affected_doc_ids:
            self._delete_chroma_chunks(
                [
                    chunk.chunk_id
                    for chunk in old_chunks.values()
                    if chunk.parent_id in affected_doc_ids or chunk.doc_id in affected_doc_ids
                ]
            )

        retained_chunks = [
            chunk
            for chunk in old_chunks.values()
            if chunk.parent_id not in affected_doc_ids and chunk.doc_id not in affected_doc_ids
        ]
        replacement_chunks = self._split_documents(new_or_updated)
        chunks = [*retained_chunks, *replacement_chunks]

        self._write_parent_documents(documents)
        self._write_chunks_index(chunks)
        self._write_bm25(chunks)
        self._write_chroma(replacement_chunks)
        self._write_index_state(len(documents), len(chunks))

        return {
            "mode": "sync",
            "documents": len(documents),
            "chunks": len(chunks),
            "new_documents": sum(1 for document in new_or_updated if document.doc_id not in old_parents),
            "updated_documents": sum(1 for document in new_or_updated if document.doc_id in old_parents),
            "deleted_documents": len(deleted_doc_ids),
            "unchanged_documents": len(documents) - len(new_or_updated),
        }

    def _data_dirs(self) -> list[Path]:
        return [Path(item).expanduser() for item in self.config.data_dirs_list]

    def _write_bm25(self, chunks: list[KnowledgeChunk]) -> None:
        index = BM25ChunkIndex.from_chunks(chunks)
        self._bm25_path().parent.mkdir(parents=True, exist_ok=True)
        with self._bm25_path().open("wb") as file:
            pickle.dump(index, file)

    def _write_parent_documents(self, documents: list[KnowledgeDocument]) -> None:
        parents = {document.doc_id: document for document in documents}
        self._parent_documents_path().parent.mkdir(parents=True, exist_ok=True)
        with self._parent_documents_path().open("wb") as file:
            pickle.dump(parents, file)

    def _write_chunks_index(self, chunks: list[KnowledgeChunk]) -> None:
        chunks_by_id = {chunk.chunk_id: chunk for chunk in chunks}
        self._chunks_index_path().parent.mkdir(parents=True, exist_ok=True)
        with self._chunks_index_path().open("wb") as file:
            pickle.dump(chunks_by_id, file)

    def _write_chroma(self, chunks: list[KnowledgeChunk]) -> None:
        if not chunks:
            return
        import chromadb

        client = chromadb.PersistentClient(path=self.config.chroma_path)
        collection = client.get_or_create_collection(self.config.collection)
        texts = [_chunk_embedding_text(chunk) for chunk in chunks]
        embeddings = self.embedding_provider.embed_documents(texts)
        collection.add(
            ids=[chunk.chunk_id for chunk in chunks],
            embeddings=embeddings,
            documents=[chunk.content for chunk in chunks],
            metadatas=[_chunk_metadata(chunk) for chunk in chunks],
        )

    def _split_documents(self, documents: list[KnowledgeDocument]) -> list[KnowledgeChunk]:
        chunks: list[KnowledgeChunk] = []
        for document in documents:
            strategy, target_chars, overlap_chars = self._chunking_for(document.path)
            chunks.extend(
                split_markdown(
                    doc_id=document.doc_id,
                    path=document.path,
                    title=document.title,
                    domain=document.domain,
                    category=document.category,
                    tags=document.tags,
                    content=document.content,
                    parent_content_hash=document.content_hash,
                    target_chars=target_chars,
                    overlap_chars=overlap_chars,
                    strategy=strategy,
                )
            )
        return chunks

    def _chunking_for(self, path: str) -> tuple[str, int, int]:
        for source in sorted(self.source_configs, key=lambda item: len(item.path_prefix), reverse=True):
            prefix = source.path_prefix.rstrip("/") + "/"
            if not source.enabled or not path.startswith(prefix):
                continue
            if source.chunk_strategy == "fixed":
                size = max(150, min(900, source.chunk_size))
                return "fixed", size, max(1, size // 6)
            return "heading", 900, 150
        return "heading", 900, 150

    def _delete_chroma_chunks(self, chunk_ids: list[str]) -> None:
        if not chunk_ids:
            return
        try:
            import chromadb

            client = chromadb.PersistentClient(path=self.config.chroma_path)
            collection = client.get_collection(self.config.collection)
            collection.delete(ids=chunk_ids)
        except Exception:
            return

    def _missing_required_indexes(self) -> bool:
        return not all(
            path.exists()
            for path in [
                self._bm25_path(),
                self._parent_documents_path(),
                self._chunks_index_path(),
            ]
        )

    def _load_parent_documents(self) -> dict[str, KnowledgeDocument]:
        parents = _load_pickle(self._parent_documents_path())
        if isinstance(parents, dict):
            return parents
        return {}

    def _load_chunks_index(self) -> dict[str, KnowledgeChunk]:
        chunks = _load_pickle(self._chunks_index_path())
        if isinstance(chunks, dict):
            return chunks
        return {}

    def _bm25_path(self) -> Path:
        return Path(self.config.chroma_path) / "bm25_index.pkl"

    def _parent_documents_path(self) -> Path:
        return Path(self.config.chroma_path) / "parent_documents.pkl"

    def _chunks_index_path(self) -> Path:
        return Path(self.config.chroma_path) / "chunks_index.pkl"

    def _index_state_path(self) -> Path:
        return Path(self.config.chroma_path) / "index_state.json"

    def _write_index_state(self, document_count: int, chunk_count: int) -> None:
        path = self._index_state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "generation": uuid4().hex,
            "collection": self.config.collection,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "document_count": document_count,
            "chunk_count": chunk_count,
        }
        temporary_path = path.with_suffix(".json.tmp")
        temporary_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary_path.replace(path)


def _chunk_embedding_text(chunk: KnowledgeChunk) -> str:
    return f"{chunk.title}\n{chunk.heading_breadcrumb}\n{chunk.content}"


def _chunk_metadata(chunk: KnowledgeChunk) -> dict[str, str]:
    return {
        "doc_id": chunk.doc_id,
        "chunk_id": chunk.chunk_id,
        "path": chunk.path,
        "title": chunk.title,
        "domain": chunk.domain,
        "category": chunk.category or "",
        "tags": ",".join(chunk.tags),
        "heading_breadcrumb": chunk.heading_breadcrumb,
        "content_hash": chunk.content_hash,
        "parent_id": chunk.parent_id,
        "parent_path": chunk.parent_path,
        "parent_title": chunk.parent_title,
        "parent_content_hash": chunk.parent_content_hash,
    }


def _load_pickle(path: Path) -> Any:
    try:
        with path.open("rb") as file:
            return pickle.load(file)
    except Exception:
        return None
