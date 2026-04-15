"""Tests for MCPManager client lifecycle, resources, and prompts APIs."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lifeops.tools.mcp.manager import MCPManager
from lifeops.tools.mcp.types import MCPPromptInfo, MCPResourceInfo, MCPServerConfig


def _make_config() -> MCPServerConfig:
    return MCPServerConfig(transport="stdio", command="docker", args=["run", "-i", "--rm"])


def _make_resource_info(
    server_name: str = "github",
    uri: str = "mcp://github/repos/owner/repo",
    name: str = "repo",
    description: str = "仓库信息",
    mime_type: str | None = "text/plain",
) -> MCPResourceInfo:
    return MCPResourceInfo(
        server_name=server_name,
        uri=uri,
        name=name,
        description=description,
        mime_type=mime_type,
    )


def _make_prompt_info(
    server_name: str = "github",
    name: str = "review_pr",
    description: str = "代码审查提示词",
    arguments: list[dict] | None = None,
) -> MCPPromptInfo:
    if arguments is None:
        arguments = [{"name": "pr_url", "description": "PR 链接", "required": True}]
    return MCPPromptInfo(
        server_name=server_name,
        name=name,
        description=description,
        arguments=arguments,
    )


# --- connect_server / disconnect_server ---


async def test_connect_server_success():
    manager = MCPManager()
    manager.add_server("github", _make_config())

    mock_client = AsyncMock()
    mock_client.connect = AsyncMock()

    with patch("lifeops.tools.mcp.client.MCPClient", return_value=mock_client):
        await manager.connect_server("github")

    mock_client.connect.assert_awaited_once()
    assert manager.get_client("github") is mock_client


async def test_connect_server_unregistered():
    manager = MCPManager()
    await manager.connect_server("nonexistent")
    assert manager.get_client("nonexistent") is None


async def test_connect_server_already_connected():
    manager = MCPManager()
    manager.add_server("github", _make_config())

    mock_client = AsyncMock()
    manager._clients["github"] = mock_client

    # Should not call connect since client already exists
    await manager.connect_server("github")
    mock_client.connect.assert_not_awaited()


async def test_connect_server_failure():
    manager = MCPManager()
    manager.add_server("github", _make_config())

    mock_client = AsyncMock()
    mock_client.connect = AsyncMock(side_effect=ConnectionError("连接失败"))

    with patch("lifeops.tools.mcp.client.MCPClient", return_value=mock_client):
        with pytest.raises(ConnectionError):
            await manager.connect_server("github")

    assert manager.get_client("github") is None


async def test_disconnect_server():
    manager = MCPManager()
    manager.add_server("github", _make_config())

    mock_client = AsyncMock()
    mock_client.close = AsyncMock()
    manager._clients["github"] = mock_client

    await manager.disconnect_server("github")

    mock_client.close.assert_awaited_once()
    assert manager.get_client("github") is None


async def test_disconnect_server_not_connected():
    manager = MCPManager()
    await manager.disconnect_server("nonexistent")
    assert manager.get_client("nonexistent") is None


# --- list_mcp_resources ---


async def test_list_mcp_resources():
    manager = MCPManager()
    manager.add_server("github", _make_config())

    resources = [_make_resource_info(uri="mcp://github/repos/owner/repo")]
    mock_client = AsyncMock()
    mock_client.list_resources = AsyncMock(return_value=resources)
    manager._clients["github"] = mock_client

    result = await manager.list_mcp_resources("github")

    assert result == resources
    mock_client.list_resources.assert_awaited_once()


async def test_list_mcp_resources_not_connected():
    manager = MCPManager()
    manager.add_server("github", _make_config())

    result = await manager.list_mcp_resources("github")

    assert result == []


# --- list_mcp_prompts ---


async def test_list_mcp_prompts():
    manager = MCPManager()
    manager.add_server("github", _make_config())

    prompts = [_make_prompt_info(name="review_pr")]
    mock_client = AsyncMock()
    mock_client.list_prompts = AsyncMock(return_value=prompts)
    manager._clients["github"] = mock_client

    result = await manager.list_mcp_prompts("github")

    assert result == prompts
    mock_client.list_prompts.assert_awaited_once()


async def test_list_mcp_prompts_not_connected():
    manager = MCPManager()
    manager.add_server("github", _make_config())

    result = await manager.list_mcp_prompts("github")

    assert result == []


# --- read_resource ---


async def test_read_resource():
    manager = MCPManager()
    manager.add_server("github", _make_config())

    mock_client = AsyncMock()
    mock_client.read_resource = AsyncMock(return_value="file content here")
    manager._clients["github"] = mock_client

    result = await manager.read_resource("github", "mcp://github/repos/owner/repo")

    assert result == "file content here"
    mock_client.read_resource.assert_awaited_once_with("mcp://github/repos/owner/repo")


async def test_read_resource_not_connected():
    manager = MCPManager()
    manager.add_server("github", _make_config())

    with pytest.raises(RuntimeError, match="未连接"):
        await manager.read_resource("github", "mcp://github/repos/owner/repo")


# --- get_prompt ---


async def test_get_prompt():
    manager = MCPManager()
    manager.add_server("github", _make_config())

    mock_client = AsyncMock()
    mock_client.get_prompt = AsyncMock(return_value="[user]: Review this PR")
    manager._clients["github"] = mock_client

    result = await manager.get_prompt(
        "github", "review_pr", {"pr_url": "https://github.com/owner/repo/pull/1"}
    )

    assert result == "[user]: Review this PR"
    mock_client.get_prompt.assert_awaited_once_with(
        "review_pr", {"pr_url": "https://github.com/owner/repo/pull/1"}
    )


async def test_get_prompt_not_connected():
    manager = MCPManager()
    manager.add_server("github", _make_config())

    with pytest.raises(RuntimeError, match="未连接"):
        await manager.get_prompt("github", "review_pr")


async def test_get_prompt_without_arguments():
    manager = MCPManager()
    manager.add_server("github", _make_config())

    mock_client = AsyncMock()
    mock_client.get_prompt = AsyncMock(return_value="[user]: Review this PR")
    manager._clients["github"] = mock_client

    result = await manager.get_prompt("github", "review_pr")

    assert result == "[user]: Review this PR"
    mock_client.get_prompt.assert_awaited_once_with("review_pr", None)


# --- get_client ---


def test_get_client():
    manager = MCPManager()
    assert manager.get_client("nonexistent") is None

    mock_client = MagicMock()
    manager._clients["github"] = mock_client
    assert manager.get_client("github") is mock_client
