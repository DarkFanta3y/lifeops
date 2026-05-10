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
    store.close()


@pytest.mark.asyncio
async def test_memory_service_finalize_generates_once_and_upserts_profile(tmp_path):
    store = ConversationHistoryStoreSQLite(tmp_path / "memory.db")
    store.append_message("conv-1", "web", "user", "我想早上跑步")
    store.append_message("conv-1", "web", "assistant", "可以制定计划")
    llm = FakeLLM()
    service = MemoryService(store, llm, MemoryConfig())

    await service.finalize_conversation("conv-1")
    await service.finalize_conversation("conv-1")

    summaries = store.list_conversation_summaries()
    preferences = store.get_user_preferences()
    graph = store.get_knowledge_graph()
    store.close()

    assert llm.calls == 1
    assert summaries[0]["summary"] == "用户想建立晨跑计划。"
    assert preferences[0]["key"] == "exercise_time"
    assert graph["entities"][0]["name"] == "晨跑"


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
