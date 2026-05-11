from __future__ import annotations

import pytest

from lifeops.core.config import MemoryConfig
from lifeops.core.context_manager import ContextManager
from lifeops.llm.types import ChatResponse
from lifeops.memory.service import MemoryService
from lifeops.storage.sqlite_store import ConversationHistoryStoreSQLite


class FakeLLM:
    def __init__(self):
        self.calls = 0

    async def chat(self, messages, tools=None, **kwargs):
        self.calls += 1
        return ChatResponse(
            content=(
                '{"summary":"用户想建立晨跑计划。",'
                '"key_decisions":["优先早上跑步"],'
                '"action_items":["制定一周计划"],'
                '"topics":["健康","习惯"],'
                '"tone":"务实",'
                '"preferences":[{"key":"exercise_time","value":"早上","confidence":0.8,'
                '"evidence":"用户提到晨跑"}],'
                '"entities":[{"name":"晨跑","entity_type":"habit","attributes":{"time":"morning"}}],'
                '"relations":[{"source":"用户","target":"晨跑","relation_type":"plans",'
                '"confidence":0.8}]}'
            ),
            tool_calls=None,
        )


class TextConfidenceLLM:
    async def chat(self, messages, tools=None, **kwargs):
        return ChatResponse(
            content=(
                '{"summary":"用户想建立晨跑计划。",'
                '"importance_score":"高",'
                '"preferences":[{"key":"exercise_time","value":"早上","confidence":"高",'
                '"evidence":"用户提到晨跑"}]}'
            ),
            tool_calls=None,
        )


@pytest.mark.asyncio
async def test_memory_service_bootstrap_injects_summaries_and_preferences(tmp_path):
    store = ConversationHistoryStoreSQLite(tmp_path / "memory.db")
    store.append_message("old-conv", "web", "user", "晨跑计划")
    store.insert_or_update_conversation_summary(
        {
            "conversation_id": "old-conv",
            "summary": "用户在规划晨跑。",
            "topics": ["健康"],
        }
    )
    store.upsert_user_preferences(
        [
            {"key": "language", "value": "中文", "confidence": 0.9},
            {"key": "low", "value": "忽略", "confidence": 0.3},
        ]
    )
    context = ContextManager()
    service = MemoryService(
        store,
        FakeLLM(),
        MemoryConfig(summary_top_k=1, preference_min_confidence=0.7),
    )

    await service.bootstrap_context("帮我继续规划晨跑", "new-conv", context)

    assert context.get_content("memory:summary:old-conv") is not None
    assert "language" in (context.get_content("memory:user_preferences") or "")
    assert "low" not in (context.get_content("memory:user_preferences") or "")
    assert context.get_content("memory:summary:old-conv") in [
        entry.content for entry in context.get_l2_content()
    ]
    snapshot_count = store._conn.execute(
        "SELECT COUNT(*) FROM memory_config_snapshots"
    ).fetchone()[0]
    assert snapshot_count == 1
    store.close()


@pytest.mark.asyncio
async def test_memory_service_finalize_regenerates_when_conversation_grows(tmp_path):
    store = ConversationHistoryStoreSQLite(tmp_path / "memory.db")
    store.append_message("conv-1", "web", "user", "我想早上跑步")
    store.append_message("conv-1", "web", "assistant", "可以制定计划")
    llm = FakeLLM()
    service = MemoryService(store, llm, MemoryConfig())

    await service.finalize_conversation("conv-1")
    store.append_message("conv-1", "web", "user", "再加一个训练提醒")
    await service.finalize_conversation("conv-1")

    summaries = store.list_conversation_summaries()
    preferences = store.get_user_preferences()
    graph = store.get_knowledge_graph()
    store.close()

    assert llm.calls == 2
    assert summaries[0]["summary"] == "用户想建立晨跑计划。"
    assert preferences[0]["key"] == "exercise_time"
    assert preferences[0]["source_conversation_id"] == "conv-1"
    assert graph["entities"][0]["name"] == "晨跑"


@pytest.mark.asyncio
async def test_memory_service_finalize_accepts_text_confidence_labels(tmp_path):
    store = ConversationHistoryStoreSQLite(tmp_path / "memory.db")
    store.append_message("conv-1", "web", "user", "我想早上跑步")
    service = MemoryService(store, TextConfidenceLLM(), MemoryConfig())

    await service.finalize_conversation("conv-1")

    summaries = store.list_conversation_summaries()
    preferences = store.get_user_preferences()
    store.close()

    assert summaries[0]["importance_score"] == 0.9
    assert preferences[0]["key"] == "exercise_time"
    assert preferences[0]["confidence"] == 0.9


@pytest.mark.asyncio
async def test_memory_service_search_returns_mixed_memory(tmp_path):
    store = ConversationHistoryStoreSQLite(tmp_path / "memory.db")
    store.append_message("conv-1", "web", "user", "我喜欢晨跑")
    store.insert_or_update_conversation_summary(
        {
            "conversation_id": "conv-1",
            "summary": "用户喜欢晨跑并希望保持健康习惯。",
            "topics": ["健康"],
        }
    )
    store.upsert_user_preferences(
        [{"key": "exercise_time", "value": "早上", "confidence": 0.9}]
    )
    store.upsert_knowledge_entities(
        [{"name": "晨跑", "entity_type": "habit", "attributes": {"time": "morning"}}]
    )
    service = MemoryService(store, FakeLLM(), MemoryConfig())

    result = service.search("晨跑")
    store.close()

    assert result["summaries"][0]["conversation_id"] == "conv-1"
    assert result["preferences"][0]["key"] == "exercise_time"
    assert result["entities"][0]["name"] == "晨跑"


@pytest.mark.asyncio
async def test_memory_service_disabled_is_noop(tmp_path):
    store = ConversationHistoryStoreSQLite(tmp_path / "memory.db")
    context = ContextManager()
    service = MemoryService(store, FakeLLM(), MemoryConfig(enabled=False))

    await service.bootstrap_context("任何输入", "conv", context)
    await service.finalize_conversation("conv")

    assert context.get_l2_content() == []
    assert store.list_conversation_summaries() == []
    store.close()
