from __future__ import annotations

from lifeops.tools.mcp.servers.github import (
    create_github_mcp_config,
    get_github_mcp_server_name,
)
from lifeops.tools.mcp.servers.google_workspace import (
    create_google_workspace_mcp_config,
    get_google_workspace_mcp_server_name,
)

__all__ = [
    "create_github_mcp_config",
    "create_google_workspace_mcp_config",
    "get_github_mcp_server_name",
    "get_google_workspace_mcp_server_name",
]
