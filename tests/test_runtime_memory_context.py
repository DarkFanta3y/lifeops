from __future__ import annotations

from lifeops.core.compression_pipeline import CompressionPipeline
from lifeops.core.config import MemoryConfig
from lifeops.core.context_manager import ContextLayer, ContextManager
from lifeops.storage.sqlite_store import ConversationHistoryStoreSQLite


def test_compression_and_usage_events_can_be_queried_by_run_id(tmp_path):
    store = ConversationHistoryStoreSQLite(tmp_path / "runtime-memory.db")
    store.append_message("conv", "web", "user", "你好")

    context = ContextManager(max_tokens=100)
    context.add_content("tool_big", "x" * 800, ContextLayer.L3, token_count=200)

    result = CompressionPipeline(
        context,
        store,
        MemoryConfig(enabled=True, offload_dir=str(tmp_path / "offload")),
    ).execute("conv", run_id="run-memory")

    store.record_tool_usage("bash", success=True, duration_ms=1.0, run_id="run-memory")
    store.record_skill_usage("weekly-review", activation_type="explicit", run_id="run-memory")

    assert result["phase"] in {"offload", "trim", "summarize", "critical", "pressure"}
    assert store.list_compression_events(run_id="run-memory")
    assert store.list_tool_usage_events(run_id="run-memory")[0]["tool_name"] == "bash"
    assert store.list_skill_usage_events(run_id="run-memory")[0]["skill_name"] == "weekly-review"
