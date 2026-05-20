from __future__ import annotations

import pytest

from lifeops.agent import Agent
from lifeops.core.config import AppConfig, LLMConfig, RAGConfig, SkillsConfig
from lifeops.llm.types import ChatResponse
from lifeops.runtime.store import RuntimeStore
from lifeops.runtime.types import TraceEventType, TraceRecorder
from lifeops.storage.sqlite_store import ConversationHistoryStoreSQLite


@pytest.mark.asyncio
async def test_invalid_retrieval_route_json_does_not_block_reply(tmp_path):
    config = AppConfig(llm=LLMConfig(api_key="test-key"), skills=SkillsConfig(enabled=False))
    history_store = ConversationHistoryStoreSQLite(tmp_path / "agent.db")
    runtime = RuntimeStore(history_store)
    runtime.create_run("conv", "web", "你好", run_id="run-json")
    agent = Agent(
        config,
        history_store=history_store,
        conversation_id="conv",
        run_id="run-json",
        trace_recorder=TraceRecorder(runtime),
    )
    responses = [
        ChatResponse(content="不是 JSON", tool_calls=None),
        ChatResponse(content="你好，我可以帮你。", tool_calls=None),
    ]

    async def mock_chat(messages, tools=None, **kwargs):
        return responses.pop(0)

    agent.llm.chat = mock_chat

    assert await agent.run("你好") == "你好，我可以帮你。"
    assert TraceEventType.LLM_PARSE_ERROR.value in [
        event["event_type"] for event in runtime.list_run_events("run-json")
    ]


@pytest.mark.asyncio
async def test_rag_tool_failure_degrades_to_tool_result(tmp_path):
    config = AppConfig(
        llm=LLMConfig(api_key="test-key"),
        skills=SkillsConfig(enabled=False),
        rag=RAGConfig(enabled=True),
    )
    agent = Agent(config)

    class BrokenRetriever:
        def retrieve(self, *args, **kwargs):
            raise RuntimeError("index broken")

    agent.rag_retriever = BrokenRetriever()

    result = await agent._execute_pre_answer_tool("retrieve_knowledge", {"query": "资料"})

    assert result.success is False
    assert result.metadata["error_type"] == "rag_error"
    assert "本地知识库检索失败" in result.error
