from __future__ import annotations

import json
import pickle
import sys
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from lifeops.core.config import RAGConfig
from lifeops.rag.bm25 import BM25ChunkIndex
from lifeops.rag.indexer import RAGIndexer
from lifeops.rag.retriever import RAGRetriever
from lifeops.rag.types import KnowledgeChunk, KnowledgeDocument


class FakeEmbeddingProvider:
    model_name = "fake"

    def embed_query(self, text: str) -> list[float]:
        return [1.0]


class FakeReranker:
    model_name = "fake"

    def score(self, query: str, texts: list[str]) -> list[float]:
        return [1.0 for _ in texts]


def make_chunk(content: str) -> KnowledgeChunk:
    return KnowledgeChunk(
        doc_id="doc",
        chunk_id=f"chunk-{content}",
        path="notes/doc.md",
        title="Doc",
        domain="knowledge",
        category=None,
        tags=[],
        heading_breadcrumb="Doc",
        content=content,
        content_hash=content,
        parent_id="doc",
    )


def write_indexes(path, generation: str, content: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    with (path / "bm25_index.pkl").open("wb") as file:
        pickle.dump(BM25ChunkIndex.from_chunks([make_chunk(content)]), file)
    with (path / "parent_documents.pkl").open("wb") as file:
        pickle.dump(
            {
                "doc": KnowledgeDocument(
                    doc_id="doc",
                    path="notes/doc.md",
                    title="Doc",
                    domain="knowledge",
                    category=None,
                    tags=[],
                    source=None,
                    updated_at=None,
                    content=content,
                )
            },
            file,
        )
    with (path / "chunks_index.pkl").open("wb") as file:
        pickle.dump({"chunk": make_chunk(content)}, file)
    (path / "index_state.json").write_text(
        json.dumps({"generation": generation, "collection": "test"}),
        encoding="utf-8",
    )


def make_retriever(path) -> RAGRetriever:
    return RAGRetriever(
        RAGConfig(chroma_path=str(path), collection="test"),
        embedding_provider=FakeEmbeddingProvider(),
        reranker=FakeReranker(),
    )


def test_retriever_reuses_cache_and_reloads_on_generation_change(tmp_path, monkeypatch):
    index_path = tmp_path / "index"
    write_indexes(index_path, "one", "old")
    client_calls = 0

    class FakeClient:
        def __init__(self, path: str):
            nonlocal client_calls
            client_calls += 1

        def get_collection(self, name: str):
            return SimpleNamespace(name=name)

    monkeypatch.setitem(sys.modules, "chromadb", SimpleNamespace(PersistentClient=FakeClient))
    retriever = make_retriever(index_path)

    first = retriever._cache_snapshot()
    second = retriever._cache_snapshot()
    assert first[0] is second[0]
    assert first[1] is second[1]
    assert client_calls == 1

    write_indexes(index_path, "two", "new")
    refreshed = retriever._cache_snapshot()
    assert refreshed[0] is not first[0]
    assert refreshed[1]["doc"].content == "new"
    assert client_calls == 2


def test_retriever_retains_cache_during_rebuild_or_failed_reload(tmp_path, monkeypatch):
    index_path = tmp_path / "index"
    write_indexes(index_path, "one", "stable")

    class FakeClient:
        def __init__(self, path: str):
            pass

        def get_collection(self, name: str):
            return SimpleNamespace(name=name)

    monkeypatch.setitem(sys.modules, "chromadb", SimpleNamespace(PersistentClient=FakeClient))
    retriever = make_retriever(index_path)
    original = retriever._cache_snapshot()

    (index_path / "index_state.json").unlink()
    assert retriever._cache_snapshot()[0] is original[0]

    (index_path / "bm25_index.pkl").write_bytes(b"broken")
    (index_path / "parent_documents.pkl").write_bytes(b"broken")
    (index_path / "index_state.json").write_text(
        json.dumps({"generation": "two", "collection": "test"}),
        encoding="utf-8",
    )

    class BrokenClient(FakeClient):
        def get_collection(self, name: str):
            raise RuntimeError("collection unavailable")

    monkeypatch.setitem(sys.modules, "chromadb", SimpleNamespace(PersistentClient=BrokenClient))
    retained = retriever._cache_snapshot()
    assert retained[0] is original[0]
    assert retained[1] is original[1]


def test_concurrent_generation_reload_happens_once(tmp_path, monkeypatch):
    index_path = tmp_path / "index"
    write_indexes(index_path, "one", "old")

    class FakeClient:
        def __init__(self, path: str):
            pass

        def get_collection(self, name: str):
            return SimpleNamespace(name=name)

    monkeypatch.setitem(sys.modules, "chromadb", SimpleNamespace(PersistentClient=FakeClient))
    retriever = make_retriever(index_path)
    retriever._cache_snapshot()
    write_indexes(index_path, "two", "new")
    reload_count = 0
    original_reload = retriever._reload_cache

    def counted_reload(signature):
        nonlocal reload_count
        reload_count += 1
        original_reload(signature)

    monkeypatch.setattr(retriever, "_reload_cache", counted_reload)
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(lambda _: retriever._cache_snapshot(), range(8)))

    assert reload_count == 1


def test_index_state_is_written_atomically(tmp_path):
    index_path = tmp_path / "index"
    indexer = RAGIndexer(
        RAGConfig(chroma_path=str(index_path), collection="test"),
        embedding_provider=FakeEmbeddingProvider(),
    )
    indexer._write_index_state(document_count=2, chunk_count=5)

    payload = json.loads((index_path / "index_state.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["collection"] == "test"
    assert payload["document_count"] == 2
    assert payload["chunk_count"] == 5
    assert payload["generation"]
    assert not (index_path / "index_state.json.tmp").exists()
