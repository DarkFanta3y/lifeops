from __future__ import annotations

from lifeops.tools.mcp.types import MCPServerConfig

PACKAGE_NAME = "12306-mcp"


def create_12306_mcp_config() -> MCPServerConfig:
    """创建 12306 MCP Server 的默认配置（npx stdio 模式）。

    12306 MCP Server 提供以下功能：
    - 查询 12306 购票信息（get-tickets）
    - 过滤列车信息
    - 过站查询（get-train-route-stations）
    - 中转换乘查询（get-interline-tickets）
    - 车站查询相关工具（get-stations-code-in-city, get-station-code-of-citys 等）
    """
    return MCPServerConfig(
        transport="stdio",
        command="npx",
        args=[
            "-y",
            PACKAGE_NAME,
        ],
        env={},
    )


def get_12306_mcp_server_name() -> str:
    return "12306"
