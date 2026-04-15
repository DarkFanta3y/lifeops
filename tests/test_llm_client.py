from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lifeops.llm.client import LLMClient
from lifeops.llm.types import ChatResponse, Message, MessageRole


def test_message_creation():
    msg = Message(role=MessageRole.USER, content="hello")
    assert msg.role == MessageRole.USER
    assert msg.content == "hello"


def test_message_to_dict():
    msg = Message(role=MessageRole.SYSTEM, content="you are a helper")
    d = msg.to_dict()
    assert d == {"role": "system", "content": "you are a helper"}


def test_message_with_tool_calls():
    tc = {
        "id": "call_1",
        "type": "function",
        "function": {"name": "bash", "arguments": '{"command":"ls"}'},
    }
    msg = Message(role=MessageRole.ASSISTANT, content=None, tool_calls=[tc])
    d = msg.to_dict()
    assert d["tool_calls"] == [tc]


def test_tool_result_message():
    msg = Message(role=MessageRole.TOOL, content="output", tool_call_id="call_1", name="bash")
    d = msg.to_dict()
    assert d["role"] == "tool"
    assert d["tool_call_id"] == "call_1"


def test_chat_response_from_openai():
    mock_tc = MagicMock()
    mock_tc.id = "call_1"
    mock_tc.type = "function"
    mock_tc.function.name = "bash"
    mock_tc.function.arguments = '{"command":"ls"}'

    mock_choice = MagicMock()
    mock_choice.message.content = None
    mock_choice.message.tool_calls = [mock_tc]

    mock_usage = MagicMock()
    mock_usage.prompt_tokens = 100
    mock_usage.completion_tokens = 50
    mock_usage.total_tokens = 150

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_response.usage = mock_usage

    result = ChatResponse.from_openai_response(mock_response)
    assert result.content is None
    assert result.tool_calls is not None
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "bash"
    assert result.usage is not None
    assert result.usage["total_tokens"] == 150


@pytest.mark.asyncio
async def test_llm_client_chat_simple():
    mock_choice = MagicMock()
    mock_choice.message.content = "Hi there!"
    mock_choice.message.tool_calls = None

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    with patch("lifeops.llm.client.AsyncOpenAI") as mock_cls:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_cls.return_value = mock_client

        client = LLMClient(api_key="test", model="gpt-4o")
        messages = [Message(role=MessageRole.USER, content="hello")]
        response = await client.chat(messages)
        assert response.content == "Hi there!"
        assert response.tool_calls is None


@pytest.mark.asyncio
async def test_llm_client_chat_with_tools():
    from lifeops.tools.base import ToolDefinition, ToolParams

    mock_tc = MagicMock()
    mock_tc.id = "call_1"
    mock_tc.type = "function"
    mock_tc.function.name = "bash"
    mock_tc.function.arguments = '{"command":"ls"}'

    mock_choice = MagicMock()
    mock_choice.message.content = None
    mock_choice.message.tool_calls = [mock_tc]

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    with patch("lifeops.llm.client.AsyncOpenAI") as mock_cls:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_cls.return_value = mock_client

        client = LLMClient(api_key="test", model="gpt-4o")

        class BashParams(ToolParams):
            command: str

        tool_def = ToolDefinition(
            name="bash",
            description="Execute bash",
            parameters_model=BashParams,
        )

        messages = [Message(role=MessageRole.USER, content="list files")]
        response = await client.chat(messages, tools=[tool_def])
        assert response.tool_calls is not None
        assert response.tool_calls[0].name == "bash"
