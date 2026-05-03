from __future__ import annotations

import pickle
import shutil
from pathlib import Path

from lifeops.core.config import RAGConfig
from lifeops.rag.bm25 import BM25ChunkIndex
from lifeops.rag.embeddings import EmbeddingProvider, SentenceTransformerEmbeddingProvider
from lifeops.rag.loader import load_markdown_documents
from lifeops.rag.splitter import split_markdown
from lifeops.rag.types import KnowledgeChunk, KnowledgeDocument


class RAGIndexer:
    def __init__(
        self,
        config: RAGConfig,
        embedding_provider: EmbeddingProvider | None = None,
    ):
        self.config = config
        self.embedding_provider = embedding_provider or SentenceTransformerEmbeddingProvider(
            config.embedding_model
        )

    def rebuild(self) -> dict[str, int]:
        chroma_path = Path(self.config.chroma_path)
        if chroma_path.exists():
            shutil.rmtree(chroma_path)
        chroma_path.mkdir(parents=True, exist_ok=True)

        documents = load_markdown_documents(self._data_dirs())
        chunks: list[KnowledgeChunk] = []
        for document in documents:
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
                )
            )

        self._write_parent_documents(documents)
        self._write_bm25(chunks)
        self._write_chroma(chunks)
        return {"documents": len(documents), "chunks": len(chunks)}

    def _data_dirs(self) -> list[Path]:
        return [Path(item).expanduser() for item in self.config.data_dirs_list]

    def _write_bm25(self, chunks: list[KnowledgeChunk]) -> None:
        index = BM25ChunkIndex.from_chunks(chunks)
        with self._bm25_path().open("wb") as file:
            pickle.dump(index, file)

    def _write_parent_documents(self, documents: list[KnowledgeDocument]) -> None:
        parents = {document.doc_id: document for document in documents}
        with self._parent_documents_path().open("wb") as file:
            pickle.dump(parents, file)

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

    def _bm25_path(self) -> Path:
        return Path(self.config.chroma_path) / "bm25_index.pkl"

    def _parent_documents_path(self) -> Path:
        return Path(self.config.chroma_path) / "parent_documents.pkl"


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
