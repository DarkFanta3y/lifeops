"""Tests for MCP type models and naming functions."""

from __future__ import annotations

from lifeops.tools.mcp.types import (
    MCPServerConfig,
    MCPPromptInfo,
    MCPResourceInfo,
    MCPToolInfo,
    is_conflicting_name,
    make_mcp_prompt_name,
    make_mcp_resource_uri,
    make_mcp_tool_name,
)
from lifeops.tools.registry import ToolRegistry
from lifeops.tools.base import ToolDefinition, ToolParams


# --- make_mcp_tool_name ---


def test_make_mcp_tool_name_basic():
    assert make_mcp_tool_name("github", "search_repositories") == "mcp.github.search_repositories"


def test_make_mcp_tool_name_with_special_chars():
    assert make_mcp_tool_name("my-server", "my_tool") == "mcp.my-server.my_tool"


def test_make_mcp_tool_name_empty_parts():
    assert make_mcp_tool_name("", "") == "mcp.."


# --- make_mcp_resource_uri ---


def test_make_mcp_resource_uri_basic():
    assert make_mcp_resource_uri("github", "repos/owner/repo") == "mcp://github/repos/owner/repo"


def test_make_mcp_resource_uri_simple_path():
    assert make_mcp_resource_uri("fs", "readme.md") == "mcp://fs/readme.md"


def test_make_mcp_resource_uri_nested_path():
    assert make_mcp_resource_uri("github", "a/b/c") == "mcp://github/a/b/c"


def test_make_mcp_resource_uri_empty_path():
    assert make_mcp_resource_uri("github", "") == "mcp://github/"


# --- make_mcp_prompt_name ---


def test_make_mcp_prompt_name_basic():
    assert make_mcp_prompt_name("github", "review_pr") == "mcp.github.review_pr"


def test_make_mcp_prompt_name_format_matches_tool_name():
    assert make_mcp_prompt_name("s", "x") == make_mcp_tool_name("s", "x")


# --- is_conflicting_name ---


def test_is_conflicting_name_true():
    registry = ToolRegistry()
    defn = ToolDefinition(
        name="mcp.github.search",
        description="test",
        parameters_model=ToolParams,
        category="mcp",
    )
    registry.register(defn, lambda p: None)

    assert is_conflicting_name("mcp.github.search", registry) is True


def test_is_conflicting_name_false():
    registry = ToolRegistry()
    assert is_conflicting_name("nonexistent", registry) is False


def test_is_conflicting_name_empty_registry():
    registry = ToolRegistry()
    assert is_conflicting_name("any_name", registry) is False


# --- MCPServerConfig ---


def test_server_config_defaults():
    config = MCPServerConfig()
    assert config.transport == "stdio"
    assert config.command is None
    assert config.args == []
    assert config.env == {}
    assert config.url is None


def test_server_config_full():
    config = MCPServerConfig(
        transport="streamable_http",
        command="docker",
        args=["run"],
        env={"KEY": "value"},
        url="http://localhost:8080",
    )
    assert config.transport == "streamable_http"
    assert config.command == "docker"
    assert config.args == ["run"]
    assert config.env == {"KEY": "value"}
    assert config.url == "http://localhost:8080"


def test_server_config_minimal():
    config = MCPServerConfig(command="npx")
    assert config.transport == "stdio"
    assert config.command == "npx"


# --- MCPToolInfo ---


def test_tool_info_full_name():
    info = MCPToolInfo(
        server_name="github",
        original_name="search_repositories",
        description="搜索仓库",
        input_schema={"type": "object"},
    )
    assert info.full_name == "mcp.github.search_repositories"


def test_tool_info_full_name_property():
    info = MCPToolInfo(
        server_name="my-server",
        original_name="my_tool",
        description="",
        input_schema={},
    )
    assert info.full_name == "mcp.my-server.my_tool"


def test_tool_info_default_values():
    info = MCPToolInfo(
        server_name="s",
        original_name="t",
    )
    assert info.description == ""
    assert info.input_schema == {}


# --- MCPResourceInfo ---


def test_resource_info_creation():
    info = MCPResourceInfo(
        server_name="github",
        uri="mcp://github/repos/owner/repo",
        name="repo",
        description="仓库信息",
        mime_type="text/plain",
    )
    assert info.server_name == "github"
    assert info.uri == "mcp://github/repos/owner/repo"
    assert info.name == "repo"
    assert info.description == "仓库信息"
    assert info.mime_type == "text/plain"


def test_resource_info_defaults():
    info = MCPResourceInfo(
        server_name="s",
        uri="mcp://s/x",
        name="n",
    )
    assert info.description == ""
    assert info.mime_type is None


# --- MCPPromptInfo ---


def test_prompt_info_creation():
    info = MCPPromptInfo(
        server_name="github",
        name="review_pr",
        description="代码审查",
        arguments=[{"name": "pr_url", "description": "PR 链接", "required": True}],
    )
    assert info.server_name == "github"
    assert info.name == "review_pr"
    assert len(info.arguments) == 1


def test_prompt_info_defaults():
    info = MCPPromptInfo(
        server_name="s",
        name="p",
    )
    assert info.description == ""
    assert info.arguments == []
