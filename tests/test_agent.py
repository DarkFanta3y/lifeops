from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lifeops.agent import Agent, DEFAULT_SYSTEM_PROMPT
from lifeops.core.config import AppConfig, LLMConfig
from lifeops.llm.types import ChatResponse, MessageRole, ToolCallResult
from lifeops.tools.base import ToolDefinition, ToolParams, ToolResult


@pytest.fixture
def mock_config():
    return AppConfig(llm=LLMConfig(api_key="test-key", model="gpt-4o"))


def test_agent_initialization(mock_config: AppConfig):
    agent = Agent(mock_config)
    assert agent.config == mock_config
    assert len(agent.tools.list_definitions()) > 0
    assert agent.system_prompt == DEFAULT_SYSTEM_PROMPT
    assert len(agent.messages) == 0


def test_agent_custom_system_prompt(mock_config: AppConfig):
    custom_prompt = "You are a cooking assistant."
    agent = Agent(mock_config, system_prompt=custom_prompt)
    assert agent.system_prompt == custom_prompt


def test_agent_reset(mock_config: AppConfig):
    agent = Agent(mock_config)
    agent.messages.append(MagicMock())
    assert len(agent.messages) == 1

    agent.reset()
    assert len(agent.messages) == 0


def test_agent_add_tool(mock_config: AppConfig):
    agent = Agent(mock_config)
    initial_count = len(agent.tools.list_definitions())

    class CustomParams(ToolParams):
        input: str

    tool_def = ToolDefinition(
        name="custom_tool",
        description="A custom tool",
        parameters_model=CustomParams,
    )

    async def custom_handler(params: dict) -> ToolResult:
        return ToolResult(success=True, output="custom result")

    agent.add_tool(tool_def, custom_handler)

    assert len(agent.tools.list_definitions()) == initial_count + 1
    assert agent.tools.get_definition("custom_tool") is not None


@pytest.mark.asyncio
async def test_agent_simple_response(mock_config: AppConfig):
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "Hello! How can I help you?"
    mock_response.choices[0].message.tool_calls = None

    with patch("lifeops.agent.LLMClient") as MockLLM:
        mock_llm_instance = AsyncMock()
        mock_llm_instance.chat = AsyncMock(
            return_value=ChatResponse(
                content="Hello! How can I help you?",
                tool_calls=None,
            )
        )
        MockLLM.return_value = mock_llm_instance

        agent = Agent(mock_config)
        agent.llm = mock_llm_instance

        result = await agent.run("Hi there!")
        assert result == "Hello! How can I help you?"
        assert len(agent.messages) == 2
        assert agent.messages[0].role == MessageRole.USER


@pytest.mark.asyncio
async def test_agent_tool_call_loop(mock_config: AppConfig):
    call_count = 0

    async def mock_chat(messages, tools=None, **kwargs):
        nonlocal call_count
        call_count += 1

        if call_count == 1:
            return ChatResponse(
                content=None,
                tool_calls=[
                    ToolCallResult(
                        id="call_1",
                        name="bash",
                        arguments='{"command":"echo hello"}',
                        type="function",
                    )
                ],
            )
        else:
            return ChatResponse(content="The command output: hello", tool_calls=None)

    mock_llm = AsyncMock()
    mock_llm.chat = AsyncMock(side_effect=mock_chat)
    mock_llm.model = "gpt-4o"

    agent = Agent(mock_config)
    agent.llm = mock_llm

    result = await agent.run("Run echo hello")
    assert "hello" in result.lower() or "command" in result.lower()


@pytest.mark.asyncio
async def test_agent_sends_sanitized_tool_result_to_next_llm_call(mock_config: AppConfig):
    call_messages = []

    async def mock_chat(messages, tools=None, **kwargs):
        call_messages.append(messages)
        if len(call_messages) == 1:
            return ChatResponse(
                content=None,
                tool_calls=[
                    ToolCallResult(
                        id="call_1",
                        name="custom_tool",
                        arguments='{"input":"openai/codex"}',
                        type="function",
                    )
                ],
            )
        return ChatResponse(content="查到了", tool_calls=None)

    async def custom_handler(params: dict) -> ToolResult:
        return ToolResult(success=True, output="repo \ud83d\ude80")

    class CustomParams(ToolParams):
        input: str

    agent = Agent(mock_config)
    agent.add_tool(
        ToolDefinition(
            name="custom_tool",
            description="A custom tool",
            parameters_model=CustomParams,
        ),
        custom_handler,
    )

    mock_llm = AsyncMock()
    mock_llm.chat = AsyncMock(side_effect=mock_chat)
    agent.llm = mock_llm

    result = await agent.run("查仓库")

    tool_message = next(msg for msg in call_messages[1] if msg.role == MessageRole.TOOL)
    assert result == "查到了"
    assert tool_message.content == "repo 🚀"
    assert tool_message.content.encode("utf-8")


@pytest.mark.asyncio
async def test_agent_unknown_tool(mock_config: AppConfig):
    async def mock_chat(messages, tools=None, **kwargs):
        return ChatResponse(
            content=None,
            tool_calls=[
                ToolCallResult(
                    id="call_1", name="nonexistent_tool", arguments="{}", type="function"
                )
            ],
        )

    mock_llm = AsyncMock()
    mock_llm.chat = AsyncMock(side_effect=mock_chat)

    agent = Agent(mock_config)
    agent.llm = mock_llm

    await agent.run("Use nonexistent tool")
    assert len(agent.messages) > 0
