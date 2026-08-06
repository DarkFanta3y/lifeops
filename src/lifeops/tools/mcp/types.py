from __future__ import annotations

import re
from hashlib import sha1
from typing import Any

from pydantic import BaseModel

from lifeops.tools.registry import ToolRegistry


MCP_TOOL_NAME_MAX_LENGTH = 64
_MCP_TOOL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


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
        """返回给 LLM 和注册中心使用的安全 wire name。"""
        return make_mcp_tool_name(self.server_name, self.original_name)

    @property
    def canonical_name(self) -> str:
        """返回策略、日志和路由使用的稳定 canonical name。"""
        return make_mcp_canonical_name(self.server_name, self.original_name)


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
    """生成只含 ASCII 字母、数字、下划线和短横线的 MCP wire name。"""
    canonical_name = make_mcp_canonical_name(server_name, tool_name)
    candidate = f"mcp_{_normalize_name_part(server_name)}_{_normalize_name_part(tool_name)}"
    raw_candidate = f"mcp_{server_name}_{tool_name}"
    if candidate == raw_candidate and len(candidate) <= MCP_TOOL_NAME_MAX_LENGTH:
        return candidate
    return _append_stable_hash(candidate, canonical_name)


def make_mcp_canonical_name(server_name: str, tool_name: str) -> str:
    """生成供策略、日志和路由使用的 mcp.<server>.<tool> 名称。"""
    return f"mcp.{server_name}.{tool_name}"


def make_disambiguated_mcp_tool_name(server_name: str, tool_name: str) -> str:
    """为规范化后发生碰撞的 MCP 工具生成带稳定 hash 的 wire name。"""
    candidate = f"mcp_{_normalize_name_part(server_name)}_{_normalize_name_part(tool_name)}"
    return _append_stable_hash(candidate, make_mcp_canonical_name(server_name, tool_name))


def _normalize_name_part(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_-]", "_", value)
    return normalized or "_"


def _append_stable_hash(candidate: str, canonical_name: str) -> str:
    digest = sha1(canonical_name.encode("utf-8")).hexdigest()[:8]
    suffix = f"_{digest}"
    return f"{candidate[: MCP_TOOL_NAME_MAX_LENGTH - len(suffix)]}{suffix}"


def make_mcp_resource_uri(server_name: str, path: str) -> str:
    """生成 mcp://<server>/<path> 格式的资源 URI。"""
    return f"mcp://{server_name}/{path}"


def make_mcp_prompt_name(server_name: str, prompt_name: str) -> str:
    """生成 mcp.<server>.<prompt> 格式的提示词全名。"""
    return f"mcp.{server_name}.{prompt_name}"


def is_conflicting_name(name: str, registry: ToolRegistry) -> bool:
    """检查给定名称是否已存在于工具注册中心（与本地工具冲突）。"""
    return registry.get_definition(name) is not None
