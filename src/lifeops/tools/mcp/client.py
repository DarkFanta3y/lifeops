from __future__ import annotations

from contextlib import AsyncExitStack
from typing import Any

import mcp.types as mcp_types
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from lifeops.tools.base import ToolResult
from lifeops.tools.mcp.manager import MCPManager, MCPServerStatus
from lifeops.tools.mcp.types import (
    MCPServerConfig,
    MCPPromptInfo,
    MCPResourceInfo,
    MCPToolInfo,
)
from lifeops.utils.logging import get_logger

logger = get_logger(__name__)


class MCPClient:
    """MCP 客户端，管理 stdio 连接与会话生命周期。

    用法::

        async with MCPClient("github", config, manager) as client:
            tools = await client.list_tools()
            result = await client.call_tool("search_repositories", {"q": "lifeops"})
    """

    def __init__(self, server_name: str, config: MCPServerConfig, manager: MCPManager) -> None:
        self._server_name = server_name
        self._config = config
        self._manager = manager
        self._session: ClientSession | None = None
        self._exit_stack: AsyncExitStack | None = None
        self._tools: list[MCPToolInfo] = []
        self._resources: list[MCPResourceInfo] = []
        self._prompts: list[MCPPromptInfo] = []

    async def connect(self) -> None:
        """连接到 MCP server（stdio 子进程），初始化会话。连接失败时更新状态为 FAILED。"""
        self._manager._status[self._server_name] = MCPServerStatus.CONNECTING
        logger.info(f"正在连接 MCP server: {self._server_name}")

        try:
            server_params = StdioServerParameters(
                command=self._config.command,
                args=self._config.args,
                env=self._config.env or None,
            )

            exit_stack = AsyncExitStack()
            self._exit_stack = exit_stack

            read_stream, write_stream = await exit_stack.enter_async_context(
                stdio_client(server_params)
            )

            session = ClientSession(read_stream, write_stream)
            self._session = await exit_stack.enter_async_context(session)

            await self._session.initialize()

            self._manager._status[self._server_name] = MCPServerStatus.READY
            logger.info(f"MCP server '{self._server_name}' 已连接并就绪")

        except Exception:
            self._manager._status[self._server_name] = MCPServerStatus.FAILED
            logger.exception(f"连接 MCP server '{self._server_name}' 失败")
            await self._cleanup()
            raise

    async def close(self) -> None:
        """关闭连接，清理子进程和会话资源。"""
        await self._cleanup()

    async def _cleanup(self) -> None:
        self._session = None
        self._tools.clear()
        self._resources.clear()
        self._prompts.clear()

        if self._exit_stack is not None:
            try:
                await self._exit_stack.aclose()
            except Exception:
                logger.exception(f"关闭 MCP server '{self._server_name}' 时出错")
            self._exit_stack = None

        self._manager._status[self._server_name] = MCPServerStatus.DISCONNECTED

    async def __aenter__(self) -> MCPClient:
        await self.connect()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()

    async def list_tools(self) -> list[MCPToolInfo]:
        self._ensure_connected()
        assert self._session is not None

        result: mcp_types.ListToolsResult = await self._session.list_tools()

        self._tools = [
            MCPToolInfo(
                server_name=self._server_name,
                original_name=tool.name,
                description=tool.description or "",
                input_schema=tool.inputSchema or {},
            )
            for tool in result.tools
        ]

        return self._tools

    async def list_resources(self) -> list[MCPResourceInfo]:
        self._ensure_connected()
        assert self._session is not None

        result: mcp_types.ListResourcesResult = await self._session.list_resources()

        self._resources = [
            MCPResourceInfo(
                server_name=self._server_name,
                uri=str(resource.uri),
                name=resource.name,
                description=resource.description or "",
                mime_type=resource.mimeType,
            )
            for resource in result.resources
        ]

        return self._resources

    async def list_prompts(self) -> list[MCPPromptInfo]:
        self._ensure_connected()
        assert self._session is not None

        result: mcp_types.ListPromptsResult = await self._session.list_prompts()

        self._prompts = [
            MCPPromptInfo(
                server_name=self._server_name,
                name=prompt.name,
                description=prompt.description or "",
                arguments=[
                    {
                        "name": arg.name,
                        "description": arg.description or "",
                        "required": arg.required or False,
                    }
                    for arg in (prompt.arguments or [])
                ],
            )
            for prompt in result.prompts
        ]

        return self._prompts

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> ToolResult:
        """调用指定工具，将 MCP CallToolResult 转换为 lifeops ToolResult。

        Args:
            tool_name: MCP server 上的原始工具名（非 full_name）。
            arguments: 工具参数字典。
        """
        self._ensure_connected()
        assert self._session is not None

        try:
            result: mcp_types.CallToolResult = await self._session.call_tool(
                name=tool_name,
                arguments=arguments,
            )
        except Exception as exc:
            logger.error(f"调用工具 '{tool_name}' 时发生异常: {exc}")
            return ToolResult(success=False, output="", error=str(exc))

        if result.isError:
            error_text = _extract_text_from_content(result.content)
            return ToolResult(
                success=False,
                output=error_text,
                error=error_text or "工具调用返回错误（无详细信息）",
            )

        output = _extract_text_from_content(result.content)
        return ToolResult(success=True, output=output)

    def _ensure_connected(self) -> None:
        if self._session is None:
            msg = (
                f"MCP client '{self._server_name}' 未连接。"
                "请先调用 connect() 或使用 async with 上下文管理器。"
            )
            raise RuntimeError(msg)


def _extract_text_from_content(content: list[mcp_types.ContentBlock]) -> str:
    """从 MCP content blocks 中提取可读文本：TextContent 取 text，其余 JSON 序列化。"""
    parts: list[str] = []
    for block in content:
        if isinstance(block, mcp_types.TextContent):
            parts.append(block.text)
        else:
            parts.append(block.model_dump_json(exclude_none=True))

    return "\n".join(parts)
