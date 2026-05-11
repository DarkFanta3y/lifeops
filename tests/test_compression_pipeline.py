from __future__ import annotations

from lifeops.core.compression_pipeline import CompressionPipeline
from lifeops.core.config import MemoryConfig
from lifeops.core.context_manager import ContextLayer, ContextManager
from lifeops.storage.sqlite_store import ConversationHistoryStoreSQLite


def test_pipeline_at_70_percent_only_records_pressure(tmp_path):
    store = ConversationHistoryStoreSQLite(tmp_path / "memory.db")
    context = ContextManager(max_tokens=100)
    context.add_content("tool_1", "x" * 280, ContextLayer.L3, token_count=70)
    pipeline = CompressionPipeline(context, store, MemoryConfig(offload_dir=str(tmp_path / "offload")))

    result = pipeline.execute("conv-1")

    assert result["phase"] == "pressure"
    assert context.get_content("tool_1") == "x" * 280
    assert store.get_memory_stats()["compression_events"] == 1
    store.close()


def test_pipeline_at_80_percent_offloads_large_l3(tmp_path):
    store = ConversationHistoryStoreSQLite(tmp_path / "memory.db")
    context = ContextManager(max_tokens=100)
    context.add_content("tool_large", "abcdef" * 80, ContextLayer.L3, token_count=81)
    pipeline = CompressionPipeline(context, store, MemoryConfig(offload_dir=str(tmp_path / "offload")))

    result = pipeline.execute("conv-1")

    assert result["phase"] == "offload"
    assert result["freed_tokens"] > 0
    assert "已卸载" in (context.get_content("tool_large") or "")
    assert list((tmp_path / "offload").glob("*.txt"))
    row = store._conn.execute("SELECT file_path FROM message_offload_metadata").fetchone()
    assert "/" not in row["file_path"]
    store.close()


def test_pipeline_at_95_percent_preserves_l1(tmp_path):
    store = ConversationHistoryStoreSQLite(tmp_path / "memory.db")
    context = ContextManager(max_tokens=100)
    context.add_content("system_prompt", "system", ContextLayer.L1, token_count=10)
    context.add_content("l2_old", "x" * 200, ContextLayer.L2, token_count=50)
    context.add_content("tool_old", "y" * 200, ContextLayer.L3, token_count=40)
    pipeline = CompressionPipeline(context, store, MemoryConfig(offload_dir=str(tmp_path / "offload")))

    result = pipeline.execute("conv-1")

    assert result["phase"] == "critical"
    assert context.get_content("system_prompt") == "system"
    assert context.used_tokens < 100
    store.close()
