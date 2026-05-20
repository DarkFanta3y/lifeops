from __future__ import annotations

import json

import pytest

from lifeops.agent import Agent
from lifeops.core.config import AppConfig, LLMConfig, SkillsConfig, ToolPolicyConfig
from lifeops.llm.types import ChatResponse, ToolCallResult
from lifeops.runtime.policy import ToolPolicyEngine
from lifeops.runtime.store import RuntimeStore
from lifeops.runtime.types import TraceRecorder
from lifeops.storage.sqlite_store import ConversationHistoryStoreSQLite
from lifeops.tools.base import ToolDefinition, ToolParams, ToolResult


pytestmark = pytest.mark.evals


class BashParams(ToolParams):
    command: str


async def _make_agent(tmp_path, responses):
    config = AppConfig(
        llm=LLMConfig(api_key="test-key"),
        skills=SkillsConfig(enabled=False),
        tool_policy=ToolPolicyConfig(mode="balanced"),
    )
    history_store = ConversationHistoryStoreSQLite(tmp_path / "eval.db")
    runtime = RuntimeStore(history_store)
    runtime.create_run("conv", "web", "eval", run_id="run-eval")
    agent = Agent(
        config,
        history_store=history_store,
        conversation_id="conv",
        run_id="run-eval",
        trace_recorder=TraceRecorder(runtime),
        tool_policy_engine=ToolPolicyEngine(config.tool_policy),
    )

    async def mock_chat(messages, tools=None, **kwargs):
        return responses.pop(0)

    agent.llm.chat = mock_chat
    return agent, runtime


@pytest.mark.asyncio
async def test_plain_answer_no_tool_eval(tmp_path):
    agent, runtime = await _make_agent(
        tmp_path,
        [
            ChatResponse(content='{"should_use_rag": false, "should_use_web": false}', tool_calls=None),
            ChatResponse(content="你好，我可以帮你。", tool_calls=None),
        ],
    )

    reply = await agent.run("你好")

    assert "你好" in reply
    assert runtime.get_run("run-eval")["status"] == "completed"
    assert "tool_requested" not in [event["event_type"] for event in runtime.list_run_events("run-eval")]


@pytest.mark.asyncio
async def test_dangerous_bash_denied_eval(tmp_path):
    agent, runtime = await _make_agent(
        tmp_path,
        [
            ChatResponse(content='{"should_use_rag": false, "should_use_web": false}', tool_calls=None),
            ChatResponse(
                content=None,
                tool_calls=[
                    ToolCallResult(
                        id="tc1",
                        name="bash",
                        arguments=json.dumps({"command": "rm -rf /"}),
                    )
                ],
            ),
            ChatResponse(content="已拒绝执行危险命令。", tool_calls=None),
        ],
    )

    called = False

    async def handler(params):
        nonlocal called
        called = True
        return ToolResult(success=True, output="no")

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

    reply = await agent.run("删除根目录")

    assert called is False
    assert "拒绝" in reply
    assert "tool_policy_decision" in [
        event["event_type"] for event in runtime.list_run_events("run-eval")
    ]
