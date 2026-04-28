from __future__ import annotations

import os

from lifeops.tools.mcp.types import MCPServerConfig

GOOGLE_WORKSPACE_MCP_PACKAGE = "workspace-mcp"

DEFAULT_PERMISSIONS = "gmail:drafts"
DEFAULT_TOOL_TIER = "core"

REQUIRED_ENV_VARS = ["GOOGLE_OAUTH_CLIENT_ID"]

OPTIONAL_ENV_VARS = [
    "GOOGLE_OAUTH_CLIENT_SECRET",
    "OAUTHLIB_INSECURE_TRANSPORT",
    "GOOGLE_MCP_CREDENTIALS_DIR",
]

PERMISSIONS_ENV_VAR = "LIFEOPS_GOOGLE_WORKSPACE_MCP_PERMISSIONS"
TOOL_TIER_ENV_VAR = "LIFEOPS_GOOGLE_WORKSPACE_MCP_TOOL_TIER"


def create_google_workspace_mcp_config() -> MCPServerConfig:
    """创建 Google Workspace MCP Server 的默认配置（uvx stdio 模式）。

    默认只启用 Gmail 草稿权限，避免未经显式配置直接发送邮件。

    Raises:
        ValueError: 如果 GOOGLE_OAUTH_CLIENT_ID 未设置
    """
    client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
    if not client_id:
        raise ValueError(
            "GOOGLE_OAUTH_CLIENT_ID 环境变量未设置。"
            "请设置 Google OAuth 客户端 ID 以使用 Google Workspace MCP Server。"
        )

    env: dict[str, str] = {"GOOGLE_OAUTH_CLIENT_ID": client_id}
    for var in OPTIONAL_ENV_VARS:
        value = os.environ.get(var)
        if value is not None:
            env[var] = value

    permissions = os.environ.get(PERMISSIONS_ENV_VAR, DEFAULT_PERMISSIONS)
    tool_tier = os.environ.get(TOOL_TIER_ENV_VAR, DEFAULT_TOOL_TIER)

    return MCPServerConfig(
        transport="stdio",
        command="uvx",
        args=[
            GOOGLE_WORKSPACE_MCP_PACKAGE,
            "--single-user",
            "--permissions",
            permissions,
            "--tool-tier",
            tool_tier,
        ],
        env=env,
    )


def get_google_workspace_mcp_server_name() -> str:
    return "google_workspace"
