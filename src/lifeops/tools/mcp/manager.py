from __future__ import annotations

import json
from enum import Enum
from typing import Any

from lifeops.tools.mcp.types import MCPResourceInfo, MCPServerConfig, MCPPromptInfo
from lifeops.utils.logging import get_logger

logger = get_logger(__name__)


class MCPServerStatus(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    READY = "ready"
    FAILED = "failed"


class MCPManager:
    """MCP server 静态注册（load_from_config）+ 动态注册（add/remove_server）。

    同时管理客户端连接（connect/disconnect），提供资源/提示词的访问 API。
    """

    def __init__(self) -> None:
        self._servers: dict[str, MCPServerConfig] = {}
        self._status: dict[str, MCPServerStatus] = {}
        self._clients: dict[str, Any] = {}  # server_name -> MCPClient

    def add_server(self, name: str, config: MCPServerConfig) -> None:
        """注册 server 配置，名称已存在时覆盖。"""
        if name in self._servers:
            logger.warning(f"MCP server '{name}' 已存在，覆盖配置")
        self._servers[name] = config
        self._status[name] = MCPServerStatus.DISCONNECTED
        logger.info(f"已注册 MCP server: {name} (transport={config.transport})")

    def remove_server(self, name: str) -> None:
        """移除 server 配置，名称不存在时打印 warning。

        注意: 不会自动断开已连接的客户端，需先调用 disconnect_server。
        """
        if name not in self._servers:
            logger.warning(f"MCP server '{name}' 不存在，无法移除")
            return
        del self._servers[name]
        self._status.pop(name, None)
        logger.info(f"已移除 MCP server: {name}")

    def load_from_config(self, servers_raw: str) -> list[str]:
        """从 JSON 字符串加载 server 配置，返回成功加载的名称列表。

        格式: {"name": {"transport": "stdio", "command": "...", "args": [...], "env": {...}}}
        """
        if not servers_raw.strip():
            logger.info("servers_raw 为空，跳过加载")
            return []

        try:
            raw_config: dict[str, Any] = json.loads(servers_raw)
        except json.JSONDecodeError as e:
            logger.error(f"解析 MCP servers JSON 失败: {e}")
            return []

        if not isinstance(raw_config, dict):
            logger.error("MCP servers JSON 顶层必须是对象（dict）")
            return []

        loaded: list[str] = []
        for name, server_data in raw_config.items():
            if not isinstance(server_data, dict):
                logger.warning(f"跳过无效的 server 配置: {name}（值不是对象）")
                continue
            try:
                config = MCPServerConfig(**server_data)
                self._servers[name] = config
                self._status[name] = MCPServerStatus.DISCONNECTED
                loaded.append(name)
                logger.info(f"已从配置加载 MCP server: {name} (transport={config.transport})")
            except Exception as e:
                logger.error(f"加载 MCP server '{name}' 配置失败: {e}")

        logger.info(f"从配置加载了 {len(loaded)}/{len(raw_config)} 个 MCP server")
        return loaded

    def get_server(self, name: str) -> MCPServerConfig | None:
        return self._servers.get(name)

    def get_status(self, name: str) -> MCPServerStatus:
        """未注册的 server 返回 DISCONNECTED。"""
        return self._status.get(name, MCPServerStatus.DISCONNECTED)

    def list_servers(self) -> list[str]:
        return list(self._servers.keys())

    async def connect_server(self, name: str) -> None:
        """创建 MCPClient 并连接到指定 server。

        如果 server 未注册或已连接，打印 warning 并跳过。
        """
        if name not in self._servers:
            logger.warning(f"无法连接: MCP server '{name}' 未注册")
            return
        if name in self._clients:
            logger.warning(f"MCP server '{name}' 已连接，跳过重复连接")
            return

        from lifeops.tools.mcp.client import MCPClient

        client = MCPClient(name, self._servers[name], self)
        try:
            await client.connect()
            self._clients[name] = client
            logger.info(f"MCP server '{name}' 连接成功")
        except Exception:
            logger.exception(f"MCP server '{name}' 连接失败")
            raise

    async def disconnect_server(self, name: str) -> None:
        """关闭指定 server 的连接并移除客户端引用。"""
        client = self._clients.pop(name, None)
        if client is None:
            logger.warning(f"MCP server '{name}' 未连接，无法断开")
            return
        await client.close()
        logger.info(f"MCP server '{name}' 已断开连接")

    def get_client(self, name: str) -> Any | None:
        """获取指定 server 的 MCPClient 实例，未连接时返回 None。"""
        return self._clients.get(name)

    async def list_mcp_resources(self, server_name: str) -> list[MCPResourceInfo]:
        """列出指定 server 的资源（需要先连接）。"""
        client = self._clients.get(server_name)
        if client is None:
            logger.warning(f"MCP server '{server_name}' 未连接，无法列出资源")
            return []
        return await client.list_resources()

    async def list_mcp_prompts(self, server_name: str) -> list[MCPPromptInfo]:
        """列出指定 server 的提示词（需要先连接）。"""
        client = self._clients.get(server_name)
        if client is None:
            logger.warning(f"MCP server '{server_name}' 未连接，无法列出提示词")
            return []
        return await client.list_prompts()

    async def read_resource(self, server_name: str, uri: str) -> str:
        """读取指定资源的内容，委托给 MCPClient。"""
        client = self._clients.get(server_name)
        if client is None:
            msg = f"MCP server '{server_name}' 未连接，无法读取资源"
            raise RuntimeError(msg)
        return await client.read_resource(uri)

    async def get_prompt(
        self, server_name: str, prompt_name: str, arguments: dict[str, str] | None = None
    ) -> str:
        """获取指定提示词的内容，委托给 MCPClient。"""
        client = self._clients.get(server_name)
        if client is None:
            msg = f"MCP server '{server_name}' 未连接，无法获取提示词"
            raise RuntimeError(msg)
        return await client.get_prompt(prompt_name, arguments)
