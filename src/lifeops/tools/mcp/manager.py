from __future__ import annotations

import json
from enum import Enum
from typing import Any

from lifeops.tools.mcp.types import MCPServerConfig
from lifeops.utils.logging import get_logger

logger = get_logger(__name__)


class MCPServerStatus(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    READY = "ready"
    FAILED = "failed"


class MCPManager:
    """MCP server 静态注册（load_from_config）+ 动态注册（add/remove_server）。"""

    def __init__(self) -> None:
        self._servers: dict[str, MCPServerConfig] = {}
        self._status: dict[str, MCPServerStatus] = {}
        # Wave 2: _sessions / _tools 将由 client/adapter 填充

    def add_server(self, name: str, config: MCPServerConfig) -> None:
        """注册 server 配置，名称已存在时覆盖。"""
        if name in self._servers:
            logger.warning(f"MCP server '{name}' 已存在，覆盖配置")
        self._servers[name] = config
        self._status[name] = MCPServerStatus.DISCONNECTED
        logger.info(f"已注册 MCP server: {name} (transport={config.transport})")

    def remove_server(self, name: str) -> None:
        """移除 server 配置，名称不存在时打印 warning。"""
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
