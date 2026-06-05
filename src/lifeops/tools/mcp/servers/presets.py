from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from lifeops.core.config import PROJECT_ROOT
from lifeops.tools.mcp.types import MCPServerConfig

NO_KEY_MCP_PRESET_NAMES = [
    "context7",
    "playwright",
    "memory",
    "sequential_thinking",
    "filesystem",
]


def get_no_key_mcp_preset_names() -> list[str]:
    return list(NO_KEY_MCP_PRESET_NAMES)


def create_no_key_mcp_preset_configs(presets: str) -> dict[str, MCPServerConfig]:
    configs: dict[str, MCPServerConfig] = {}
    for name in _parse_preset_names(presets):
        factory = _PRESET_FACTORIES.get(name)
        if factory is None:
            continue
        configs[name] = factory()
    return configs


def _parse_preset_names(presets: str) -> list[str]:
    seen: set[str] = set()
    names: list[str] = []
    for raw_name in presets.split(","):
        name = raw_name.strip().replace("-", "_")
        if not name or name in seen:
            continue
        seen.add(name)
        names.append(name)
    return names


def _npx_config(package: str, *extra_args: str) -> MCPServerConfig:
    return MCPServerConfig(
        transport="stdio",
        command="npx",
        args=["-y", package, *extra_args],
        env={},
    )


def _create_context7_config() -> MCPServerConfig:
    return _npx_config("@upstash/context7-mcp")


def _create_playwright_config() -> MCPServerConfig:
    return _npx_config("@playwright/mcp@latest")


def _create_memory_config() -> MCPServerConfig:
    return _npx_config("@modelcontextprotocol/server-memory")


def _create_sequential_thinking_config() -> MCPServerConfig:
    return _npx_config("@modelcontextprotocol/server-sequential-thinking")


def _create_filesystem_config() -> MCPServerConfig:
    roots = _filesystem_roots()
    return _npx_config("@modelcontextprotocol/server-filesystem", *roots)


def _filesystem_roots() -> list[str]:
    raw_roots = os.environ.get("LIFEOPS_FILESYSTEM_MCP_ROOTS", "").strip()
    if not raw_roots:
        return [str(PROJECT_ROOT)]
    return [
        str(Path(root.strip()).expanduser())
        for root in raw_roots.split(",")
        if root.strip()
    ]


_PRESET_FACTORIES: dict[str, Callable[[], MCPServerConfig]] = {
    "context7": _create_context7_config,
    "playwright": _create_playwright_config,
    "memory": _create_memory_config,
    "sequential_thinking": _create_sequential_thinking_config,
    "filesystem": _create_filesystem_config,
}
