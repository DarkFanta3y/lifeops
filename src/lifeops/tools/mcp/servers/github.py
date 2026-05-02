from __future__ import annotations

import os

from lifeops.tools.mcp.types import MCPServerConfig
from lifeops.utils.logging import get_logger

logger = get_logger(__name__)

# GitHub MCP Server Docker 镜像
GITHUB_MCP_SERVER_IMAGE = "ghcr.io/github/github-mcp-server"

# 必需环境变量
REQUIRED_ENV_VARS = ["GITHUB_PERSONAL_ACCESS_TOKEN"]

# 可选环境变量
OPTIONAL_ENV_VARS = [
    "GITHUB_TOOLSETS",
    "GITHUB_TOOLS",
    "GITHUB_READ_ONLY",
    "GITHUB_LOCKDOWN_MODE",
    "GITHUB_INSIDERS",
    "GITHUB_HOST",
]


def create_github_mcp_config() -> MCPServerConfig:
    """创建 GitHub MCP Server 的默认配置（Docker stdio 模式）

    Raises:
        ValueError: 如果 GITHUB_PERSONAL_ACCESS_TOKEN 未设置
    """
    token = os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN")
    if not token:
        raise ValueError(
            "GITHUB_PERSONAL_ACCESS_TOKEN 环境变量未设置。"
            "请设置此变量以使用 GitHub MCP Server。"
            "获取 token: https://github.com/settings/tokens"
        )

    # 构建环境变量映射
    env: dict[str, str] = {"GITHUB_PERSONAL_ACCESS_TOKEN": token}
    for var in OPTIONAL_ENV_VARS:
        value = os.environ.get(var)
        if value is not None:
            env[var] = value

    return MCPServerConfig(
        transport="stdio",
        command="docker",
        args=[
            "run",
            "-i",
            "--rm",
            "-e",
            "GITHUB_PERSONAL_ACCESS_TOKEN",
            GITHUB_MCP_SERVER_IMAGE,
        ],
        env=env,
    )


def get_github_mcp_server_name() -> str:
    return "github"
