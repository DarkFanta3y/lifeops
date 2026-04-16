from __future__ import annotations

import asyncio
import os
import sys
from typing import Any

import anyio
import anyio.lowlevel
import mcp.types as mcp_types
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from anyio.streams.text import TextReceiveStream
from mcp.client.session import ClientSession
from mcp.shared.message import SessionMessage

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

    # 进程终止前的等待超时（秒）
    _TERMINATION_TIMEOUT = 2.0

    def __init__(self, server_name: str, config: MCPServerConfig, manager: MCPManager) -> None:
        self._server_name = server_name
        self._config = config
        self._manager = manager
        self._session: ClientSession | None = None
        self._process: anyio.abc.Process | None = None
        self._read_stream: MemoryObjectReceiveStream[SessionMessage | Exception] | None = None
        self._write_stream: MemoryObjectSendStream[SessionMessage] | None = None
        self._read_stream_writer: MemoryObjectSendStream[SessionMessage | Exception] | None = None
        self._write_stream_reader: MemoryObjectReceiveStream[SessionMessage] | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._writer_task: asyncio.Task[None] | None = None
        self._tools: list[MCPToolInfo] = []
        self._resources: list[MCPResourceInfo] = []
        self._prompts: list[MCPPromptInfo] = []

    async def connect(self) -> None:
        """连接到 MCP server（stdio 子进程），初始化会话。连接失败时更新状态为 FAILED。"""
        self._manager._status[self._server_name] = MCPServerStatus.CONNECTING
        logger.info(f"正在连接 MCP server: {self._server_name}")

        try:
            self._setup_memory_streams()
            await self._start_process()
            self._start_io_tasks()

            session = ClientSession(self._read_stream, self._write_stream)  # type: ignore[arg-type]
            self._session = await session.__aenter__()

            await self._session.initialize()

            self._manager._status[self._server_name] = MCPServerStatus.READY
            logger.info(f"MCP server '{self._server_name}' 已连接并就绪")

        except Exception:
            self._manager._status[self._server_name] = MCPServerStatus.FAILED
            logger.exception(f"连接 MCP server '{self._server_name}' 失败")
            await self._cleanup()
            raise

    def _setup_memory_streams(self) -> None:
        """创建 anyio 内存流用于进程 I/O 与 ClientSession 之间的消息传递。"""
        self._read_stream_writer, self._read_stream = anyio.create_memory_object_stream(0)
        self._write_stream, self._write_stream_reader = anyio.create_memory_object_stream(0)

    async def _start_process(self) -> None:
        """启动子进程，使用配置中的 command/args/env。"""
        env = self._build_env()
        self._process = await anyio.open_process(
            [self._config.command, *self._config.args],
            env=env,
            stderr=sys.stderr,
            start_new_session=True,
        )

    def _build_env(self) -> dict[str, str]:
        """合并默认环境变量与用户配置的 env。"""
        base = _get_default_environment()
        if self._config.env:
            base.update(self._config.env)
        return base

    def _start_io_tasks(self) -> None:
        """启动 stdout 读取和 stdin 写入的后台任务。"""
        loop = asyncio.get_running_loop()
        self._reader_task = loop.create_task(self._stdout_reader())
        self._writer_task = loop.create_task(self._stdin_writer())

    async def _stdout_reader(self) -> None:
        """从子进程 stdout 读取 JSONRPC 行，解析后写入内存流供 ClientSession 消费。"""
        assert self._process is not None
        assert self._process.stdout is not None
        assert self._read_stream_writer is not None

        try:
            async with self._read_stream_writer:
                buffer = ""
                async for chunk in TextReceiveStream(self._process.stdout):
                    lines = (buffer + chunk).split("\n")
                    buffer = lines.pop()

                    for line in lines:
                        try:
                            message = mcp_types.JSONRPCMessage.model_validate_json(line)
                        except Exception:
                            logger.exception("解析 JSONRPC 消息失败")
                            await self._read_stream_writer.send(
                                ValueError(f"无法解析 JSONRPC 消息: {line[:120]}")
                            )
                            continue

                        session_message = SessionMessage(message)
                        await self._read_stream_writer.send(session_message)
        except anyio.ClosedResourceError:
            await anyio.lowlevel.checkpoint()

    async def _stdin_writer(self) -> None:
        """从内存流读取 SessionMessage，序列化后写入子进程 stdin。"""
        assert self._process is not None
        assert self._process.stdin is not None
        assert self._write_stream_reader is not None

        try:
            async with self._write_stream_reader:
                async for session_message in self._write_stream_reader:
                    json_str = session_message.message.model_dump_json(
                        by_alias=True, exclude_none=True
                    )
                    await self._process.stdin.send((json_str + "\n").encode())
        except anyio.ClosedResourceError:
            await anyio.lowlevel.checkpoint()

    async def close(self) -> None:
        """关闭连接，清理子进程和会话资源。"""
        await self._cleanup()

    async def _cleanup(self) -> None:
        """清理所有资源：关闭会话、终止进程、取消任务、关闭流。"""
        if self._session is not None:
            try:
                await self._session.__aexit__(None, None, None)
            except Exception:
                logger.debug(f"关闭 MCP session '{self._server_name}' 时出错（可忽略）")
            self._session = None

        self._tools.clear()
        self._resources.clear()
        self._prompts.clear()

        await self._terminate_process()
        await self._cancel_io_tasks()
        await self._close_streams()

        self._manager._status[self._server_name] = MCPServerStatus.DISCONNECTED

    async def _terminate_process(self) -> None:
        """关闭子进程 stdin，等待退出，超时后强制终止。"""
        if self._process is None:
            return

        if self._process.stdin is not None:
            try:
                await self._process.stdin.aclose()
            except Exception:
                pass

        try:
            with anyio.fail_after(self._TERMINATION_TIMEOUT):
                await self._process.wait()
        except TimeoutError:
            self._process.kill()
            await self._process.wait()
        except ProcessLookupError:
            pass

    async def _cancel_io_tasks(self) -> None:
        """取消并等待 I/O 后台任务完成。"""
        for task in (self._reader_task, self._writer_task):
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._reader_task = None
        self._writer_task = None

    async def _close_streams(self) -> None:
        """关闭所有内存流。"""
        for stream in (
            self._read_stream,
            self._write_stream,
            self._read_stream_writer,
            self._write_stream_reader,
        ):
            if stream is not None:
                try:
                    await stream.aclose()
                except Exception:
                    pass
        self._read_stream = None
        self._write_stream = None
        self._read_stream_writer = None
        self._write_stream_reader = None
        self._process = None

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

    async def read_resource(self, uri: str) -> str:
        """读取指定资源的内容，返回文本内容。

        Args:
            uri: 资源 URI（如 `mcp://github/repos/owner/repo`）。
        """
        self._ensure_connected()
        assert self._session is not None

        result: mcp_types.ReadResourceResult = await self._session.read_resource(
            uri=mcp_types.AnyUrl(uri),
        )

        texts: list[str] = []
        for content in result.contents:
            if isinstance(content, mcp_types.TextResourceContents):
                texts.append(content.text)
            elif isinstance(content, mcp_types.BlobResourceContents):
                texts.append(content.blob)
            else:
                texts.append(content.model_dump_json(exclude_none=True))

        return "\n".join(texts)

    async def get_prompt(self, name: str, arguments: dict[str, str] | None = None) -> str:
        """获取指定提示词的内容，返回格式化的提示词文本。

        Args:
            name: MCP server 上的原始提示词名称。
            arguments: 提示词参数字典。
        """
        self._ensure_connected()
        assert self._session is not None

        result: mcp_types.GetPromptResult = await self._session.get_prompt(
            name=name,
            arguments=arguments,
        )

        parts: list[str] = []
        if result.description:
            parts.append(f"# {result.description}")

        for msg in result.messages:
            role = msg.role
            content = msg.content
            if isinstance(content, mcp_types.TextContent):
                parts.append(f"[{role}]: {content.text}")
            else:
                parts.append(f"[{role}]: {content.model_dump_json(exclude_none=True)}")

        return "\n\n".join(parts)

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


_DEFAULT_ENV_VARS = ["HOME", "LOGNAME", "PATH", "SHELL", "TERM", "USER"]


def _get_default_environment() -> dict[str, str]:
    """返回默认的安全环境变量（仅 Linux/macOS）。"""
    env: dict[str, str] = {}
    for key in _DEFAULT_ENV_VARS:
        value = os.environ.get(key)
        if value is not None and not value.startswith("()"):
            env[key] = value
    return env
