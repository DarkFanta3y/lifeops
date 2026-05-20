from __future__ import annotations

import json

import pytest

from lifeops.agent import Agent
from lifeops.core.config import AppConfig, LLMConfig, SkillsConfig, ToolPolicyConfig
from lifeops.llm.types import ChatResponse, ToolCallResult
from lifeops.runtime.policy import ToolPolicyEngine
from lifeops.runtime.store import RuntimeStore
from lifeops.runtime.types import TraceEventType, TraceRecorder
from lifeops.storage.sqlite_store import ConversationHistoryStoreSQLite
from lifeops.tools.base import ToolDefinition, ToolParams, ToolResult


class BashParams(ToolParams):
    command: str


@pytest.mark.asyncio
async def test_agent_policy_denies_dangerous_tool_before_handler_runs(tmp_path):
    config = AppConfig(
        llm=LLMConfig(api_key="test-key"),
        skills=SkillsConfig(enabled=False),
        tool_policy=ToolPolicyConfig(mode="balanced"),
    )
    history_store = ConversationHistoryStoreSQLite(tmp_path / "agent.db")
    runtime = RuntimeStore(history_store)
    runtime.create_run("conv", "web", "危险命令", run_id="run-deny")
    agent = Agent(
        config,
        history_store=history_store,
        conversation_id="conv",
        run_id="run-deny",
        trace_recorder=TraceRecorder(runtime),
        tool_policy_engine=ToolPolicyEngine(config.tool_policy),
    )
    called = False

    async def handler(params):
        nonlocal called
        called = True
        return ToolResult(success=True, output="should not run")

    agent.tools.register(
        ToolDefinition(
            name="bash",
            description="bash",
            parameters_model=BashParams,
            canonical_name="builtin.bash",
            risk_level="high",
        ),
        handler,
    )

    result = await agent._execute_tool_call_result(
        ToolCallResult(
            id="tc-deny",
            name="bash",
            arguments=json.dumps({"command": "rm -rf /"}, ensure_ascii=False),
        )
    )

    assert called is False
    assert result.success is False
    assert result.metadata["policy_action"] == "deny"
    events = runtime.list_run_events("run-deny")
    assert TraceEventType.TOOL_POLICY_DECISION.value in [event["event_type"] for event in events]


@pytest.mark.asyncio
async def test_agent_records_run_failure_on_max_iterations(tmp_path):
    config = AppConfig(llm=LLMConfig(api_key="test-key"), skills=SkillsConfig(enabled=False))
    history_store = ConversationHistoryStoreSQLite(tmp_path / "agent.db")
    runtime = RuntimeStore(history_store)
    runtime.create_run("conv", "web", "循环", run_id="run-loop")
    agent = Agent(
        config,
        history_store=history_store,
        conversation_id="conv",
        run_id="run-loop",
        trace_recorder=TraceRecorder(runtime),
    )
    agent.max_iterations = 1

    async def mock_chat(messages, tools=None, **kwargs):
        return ChatResponse(
            content=None,
            tool_calls=[
                ToolCallResult(id="tc-loop", name="missing_tool", arguments="{}"),
            ],
        )

    agent.llm.chat = mock_chat

    reply = await agent.run("循环")

    run = runtime.get_run("run-loop")
    assert run["status"] == "failed"
    assert run["error_type"] == "max_iterations_reached"
    assert "已达到最大迭代次数" in reply
