"""Tests for MCPClient connection failure handling and error conversion."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lifeops.tools.mcp.manager import MCPManager, MCPServerStatus
from lifeops.tools.mcp.client import MCPClient, _extract_text_from_content
from lifeops.tools.mcp.types import MCPServerConfig


def _make_config() -> MCPServerConfig:
    return MCPServerConfig(
        transport="stdio",
        command="docker",
        args=["run", "-i", "--rm"],
        env={"TEST_TOKEN": "xxx"},
    )


def _make_manager() -> MCPManager:
    manager = MCPManager()
    manager.add_server("test-server", _make_config())
    return manager


# --- connect failure ---


async def test_connect_failure_sets_status_failed():
    manager = _make_manager()
    client = MCPClient("test-server", _make_config(), manager)

    with patch("lifeops.tools.mcp.client.stdio_client", side_effect=ConnectionError("拒绝连接")):
        with patch("lifeops.tools.mcp.client.AsyncExitStack") as mock_stack_cls:
            mock_stack = AsyncMock()
            mock_stack.enter_async_context = AsyncMock(side_effect=ConnectionError("拒绝连接"))
            mock_stack.aclose = AsyncMock()
            mock_stack_cls.return_value = mock_stack

            with pytest.raises(ConnectionError, match="拒绝连接"):
                await client.connect()

    assert manager.get_status("test-server") == MCPServerStatus.DISCONNECTED


async def test_connect_failure_does_not_create_session():
    manager = _make_manager()
    client = MCPClient("test-server", _make_config(), manager)

    with patch("lifeops.tools.mcp.client.AsyncExitStack") as mock_stack_cls:
        mock_stack = AsyncMock()
        mock_stack.enter_async_context = AsyncMock(side_effect=OSError("子进程启动失败"))
        mock_stack.aclose = AsyncMock()
        mock_stack_cls.return_value = mock_stack

        with pytest.raises(OSError, match="子进程启动失败"):
            await client.connect()

    assert client._session is None


# --- _ensure_connected ---


async def test_ensure_connected_raises_when_not_connected():
    manager = _make_manager()
    client = MCPClient("test-server", _make_config(), manager)

    with pytest.raises(RuntimeError, match="未连接"):
        await client.list_tools()


async def test_ensure_connected_list_resources_raises():
    manager = _make_manager()
    client = MCPClient("test-server", _make_config(), manager)

    with pytest.raises(RuntimeError, match="未连接"):
        await client.list_resources()


async def test_ensure_connected_list_prompts_raises():
    manager = _make_manager()
    client = MCPClient("test-server", _make_config(), manager)

    with pytest.raises(RuntimeError, match="未连接"):
        await client.list_prompts()


async def test_ensure_connected_call_tool_raises():
    manager = _make_manager()
    client = MCPClient("test-server", _make_config(), manager)

    with pytest.raises(RuntimeError, match="未连接"):
        await client.call_tool("tool_a", {})


async def test_ensure_connected_read_resource_raises():
    manager = _make_manager()
    client = MCPClient("test-server", _make_config(), manager)

    with pytest.raises(RuntimeError, match="未连接"):
        await client.read_resource("mcp://test/x")


async def test_ensure_connected_get_prompt_raises():
    manager = _make_manager()
    client = MCPClient("test-server", _make_config(), manager)

    with pytest.raises(RuntimeError, match="未连接"):
        await client.get_prompt("prompt_a")


# --- call_tool error handling ---


async def test_call_tool_returns_error_on_exception():
    manager = _make_manager()
    client = MCPClient("test-server", _make_config(), manager)

    mock_session = AsyncMock()
    mock_session.call_tool = AsyncMock(side_effect=RuntimeError("SDK 错误"))
    client._session = mock_session

    result = await client.call_tool("failing_tool", {"q": "test"})

    assert result.success is False
    assert "SDK 错误" in result.error


async def test_call_tool_returns_error_on_is_error():
    manager = _make_manager()
    client = MCPClient("test-server", _make_config(), manager)

    import mcp.types as mcp_types

    text_block = mcp_types.TextContent(type="text", text="something went wrong")
    mock_result = MagicMock()
    mock_result.isError = True
    mock_result.content = [text_block]

    mock_session = AsyncMock()
    mock_session.call_tool = AsyncMock(return_value=mock_result)
    client._session = mock_session

    result = await client.call_tool("failing_tool", {})

    assert result.success is False
    assert "something went wrong" in result.output


async def test_call_tool_success():
    manager = _make_manager()
    client = MCPClient("test-server", _make_config(), manager)

    import mcp.types as mcp_types

    text_block = mcp_types.TextContent(type="text", text='{"name": "lifeops"}')
    mock_result = MagicMock()
    mock_result.isError = False
    mock_result.content = [text_block]

    mock_session = AsyncMock()
    mock_session.call_tool = AsyncMock(return_value=mock_result)
    client._session = mock_session

    result = await client.call_tool("search", {"q": "test"})

    assert result.success is True
    assert '{"name": "lifeops"}' in result.output


# --- close / cleanup ---


async def test_close_clears_session_and_tools():
    manager = _make_manager()
    client = MCPClient("test-server", _make_config(), manager)

    mock_session = AsyncMock()
    client._session = mock_session
    client._tools = [MagicMock()]
    client._resources = [MagicMock()]
    client._prompts = [MagicMock()]

    mock_stack = AsyncMock()
    mock_stack.aclose = AsyncMock()
    client._exit_stack = mock_stack

    await client.close()

    assert client._session is None
    assert len(client._tools) == 0
    assert len(client._resources) == 0
    assert len(client._prompts) == 0
    assert client._exit_stack is None
    assert manager.get_status("test-server") == MCPServerStatus.DISCONNECTED


async def test_close_without_exit_stack():
    manager = _make_manager()
    client = MCPClient("test-server", _make_config(), manager)
    client._session = None
    client._exit_stack = None

    await client.close()

    assert client._session is None
    assert client._exit_stack is None


async def test_cleanup_handles_exit_stack_error():
    manager = _make_manager()
    client = MCPClient("test-server", _make_config(), manager)

    mock_stack = AsyncMock()
    mock_stack.aclose = AsyncMock(side_effect=RuntimeError("清理失败"))
    client._exit_stack = mock_stack

    await client.close()

    assert client._exit_stack is None
    assert manager.get_status("test-server") == MCPServerStatus.DISCONNECTED


# --- _extract_text_from_content ---


def test_extract_text_from_text_content():
    import mcp.types as mcp_types

    blocks = [
        mcp_types.TextContent(type="text", text="hello"),
        mcp_types.TextContent(type="text", text="world"),
    ]
    assert _extract_text_from_content(blocks) == "hello\nworld"


def test_extract_text_from_mixed_content():
    import mcp.types as mcp_types

    blocks = [
        mcp_types.TextContent(type="text", text="hello"),
        mcp_types.ImageContent(type="image", data="base64data", mimeType="image/png"),
    ]
    result = _extract_text_from_content(blocks)
    assert "hello" in result
    assert "base64data" in result


def test_extract_text_from_empty_list():
    assert _extract_text_from_content([]) == ""


# --- context manager ---


async def test_context_manager_connects_and_closes():
    manager = _make_manager()
    client = MCPClient("test-server", _make_config(), manager)

    mock_session = AsyncMock()
    mock_session.initialize = AsyncMock()
    mock_session.list_tools = AsyncMock(return_value=MagicMock(tools=[]))

    with patch("lifeops.tools.mcp.client.stdio_client") as mock_stdio:
        mock_read = AsyncMock()
        mock_write = AsyncMock()
        mock_stdio.return_value = (mock_read, mock_write)

        with patch("lifeops.tools.mcp.client.ClientSession", return_value=mock_session):
            with patch("lifeops.tools.mcp.client.AsyncExitStack") as mock_stack_cls:
                mock_stack = AsyncMock()
                mock_stack.enter_async_context = AsyncMock(
                    side_effect=[(mock_read, mock_write), mock_session]
                )
                mock_stack.aclose = AsyncMock()
                mock_stack_cls.return_value = mock_stack

                async with client:
                    pass

    assert manager.get_status("test-server") == MCPServerStatus.DISCONNECTED
