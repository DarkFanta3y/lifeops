from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from lifeops.tools.registry import ToolRegistry


class MCPServerConfig(BaseModel):
    """单个 MCP server 的配置。"""

    transport: str = "stdio"  # stdio | streamable_http
    command: str | None = None  # stdio 传输的可执行命令
    args: list[str] = []  # 命令参数
    env: dict[str, str] = {}  # 环境变量
    url: str | None = None  # HTTP 传输的 URL


class MCPToolInfo(BaseModel):
    """MCP 工具的内部表示。"""

    server_name: str  # server 标识
    original_name: str  # MCP server 返回的原始工具名
    description: str = ""
    input_schema: dict[str, Any] = {}  # JSON Schema

    @property
    def full_name(self) -> str:
        """返回 mcp.<server>.<tool> 格式的全名。"""
        return make_mcp_tool_name(self.server_name, self.original_name)


class MCPResourceInfo(BaseModel):
    """MCP 资源的内部表示。"""

    server_name: str
    uri: str
    name: str = ""
    description: str = ""
    mime_type: str | None = None


class MCPPromptInfo(BaseModel):
    """MCP prompt 的内部表示。"""

    server_name: str
    name: str
    description: str = ""
    arguments: list[dict[str, Any]] = []


def make_mcp_tool_name(server_name: str, tool_name: str) -> str:
    """生成 mcp.<server>.<tool> 格式的工具全名。"""
    return f"mcp.{server_name}.{tool_name}"


def make_mcp_resource_uri(server_name: str, path: str) -> str:
    """生成 mcp://<server>/<path> 格式的资源 URI。"""
    return f"mcp://{server_name}/{path}"


def make_mcp_prompt_name(server_name: str, prompt_name: str) -> str:
    """生成 mcp.<server>.<prompt> 格式的提示词全名。"""
    return f"mcp.{server_name}.{prompt_name}"


def is_conflicting_name(name: str, registry: ToolRegistry) -> bool:
    """检查给定名称是否已存在于工具注册中心（与本地工具冲突）。"""
    return registry.get_definition(name) is not None
