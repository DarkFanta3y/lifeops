from __future__ import annotations

import asyncio
from collections import deque
from time import perf_counter
from typing import Any
from uuid import uuid4

from pydantic import Field

from lifeops.core.config import AppConfig
from lifeops.tools.base import ToolDefinition, ToolParams, ToolResult
from lifeops.tools.registry import ToolRegistry
from lifeops.utils.logging import get_logger

logger = get_logger(__name__)

DEFAULT_BASH_MAX_OUTPUT_CHARS = 30000
_BACKGROUND_BUFFER_LINES = 2000


class BashParams(ToolParams):
    command: str = Field(
        min_length=1,
        description="只读诊断、测试或构建检查命令；不要传入联网、删除、重置、移动文件等危险命令。",
    )
    timeout: int = Field(default=30, ge=1, le=120, description="命令超时时间，单位秒")
    workdir: str | None = Field(
        default=None,
        min_length=1,
        pattern=r".+",
        description="可选工作目录路径",
    )
    run_in_background: bool = Field(
        default=False,
        description="是否在后台运行并立即返回 task_id；长时命令（如开发服务器）使用 true，之后用 bash_output 读取输出",
    )


class BashOutputParams(ToolParams):
    task_id: str = Field(min_length=1, description="后台任务的 task_id")
    tail_lines: int = Field(default=100, ge=1, le=2000, description="返回最近的输出行数")


class BashKillParams(ToolParams):
    task_id: str = Field(min_length=1, description="要终止的后台任务 task_id")


class BackgroundShell:
    """一个后台 shell 任务：进程 + 环形输出缓冲。随 API 进程生命周期存续。"""

    def __init__(self, task_id: str, command: str) -> None:
        self.task_id = task_id
        self.command = command
        self.process: asyncio.subprocess.Process | None = None
        self.drain_task: asyncio.Task | None = None
        self.lines: deque[str] = deque(maxlen=_BACKGROUND_BUFFER_LINES)
        self.started_at = perf_counter()
        self.finished = False

    @property
    def running(self) -> bool:
        return not self.finished and self.drain_task is not None and not self.drain_task.done()

    def status_summary(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "command": self.command,
            "running": self.running,
            "returncode": self.process.returncode if self.process else None,
            "elapsed_seconds": round(perf_counter() - self.started_at, 1),
            "buffered_lines": len(self.lines),
        }


_background_shells: dict[str, BackgroundShell] = {}


def _truncate_output(output: str, limit: int) -> tuple[str, bool]:
    if len(output) <= limit:
        return output, False
    keep = limit // 2
    omitted = len(output) - limit
    truncated = (
        output[:keep]
        + f"\n... [输出超长，已截断 {omitted} 字符，可用更精确的命令缩小范围] ...\n"
        + output[-keep:]
    )
    return truncated, True


async def _bash_handler(params: dict[str, Any]) -> ToolResult:
    validated = BashParams.model_validate(params)

    if validated.run_in_background:
        return await _start_background_shell(validated.command, validated.workdir)
    return await _run_foreground_shell(validated)


async def _run_foreground_shell(validated: BashParams) -> ToolResult:
    command = validated.command
    timeout = validated.timeout
    try:
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=validated.workdir,
        )
    except Exception as e:
        return ToolResult(success=False, output="", error=str(e))

    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        process.kill()
        try:
            await process.wait()
        except ProcessLookupError:
            pass
        return ToolResult(success=False, output="", error=f"Command timed out after {timeout}s")

    max_chars = _bash_max_output_chars()
    output, truncated = _truncate_output(stdout.decode("utf-8", errors="replace"), max_chars)
    error_output = stderr.decode("utf-8", errors="replace")
    metadata: dict[str, Any] = {}
    if truncated:
        metadata["truncated"] = True

    if process.returncode == 0:
        return ToolResult(success=True, output=output or "(no output)", metadata=metadata)
    return ToolResult(
        success=False,
        output=output,
        error=f"Exit code {process.returncode}: {error_output}",
        metadata=metadata,
    )


async def _start_background_shell(command: str, workdir: str | None) -> ToolResult:
    shell = BackgroundShell(uuid4().hex[:12], command)
    try:
        shell.process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=workdir,
        )
    except Exception as e:
        return ToolResult(success=False, output="", error=str(e))

    async def _drain() -> None:
        assert shell.process is not None and shell.process.stdout is not None
        async for raw_line in shell.process.stdout:
            shell.lines.append(raw_line.decode("utf-8", errors="replace").rstrip("\n"))
        await shell.process.wait()
        shell.finished = True

    shell.drain_task = asyncio.create_task(_drain())
    _background_shells[shell.task_id] = shell
    logger.info(f"后台任务已启动: {shell.task_id} -> {command}")
    return ToolResult(
        success=True,
        output=f"后台任务已启动 task_id={shell.task_id}，用 bash_output 读取输出、bash_kill 终止。",
        metadata={"background": True, **shell.status_summary()},
    )


async def _bash_output_handler(params: dict[str, Any]) -> ToolResult:
    validated = BashOutputParams.model_validate(params)
    shell = _background_shells.get(validated.task_id)
    if shell is None:
        return ToolResult(
            success=False, output="", error=f"Unknown background task: {validated.task_id}"
        )
    lines = list(shell.lines)[-validated.tail_lines:]
    output = "\n".join(lines) if lines else "(暂无输出)"
    return ToolResult(
        success=True,
        output=output,
        metadata=shell.status_summary(),
    )


async def _bash_kill_handler(params: dict[str, Any]) -> ToolResult:
    validated = BashKillParams.model_validate(params)
    shell = _background_shells.pop(validated.task_id, None)
    if shell is None:
        return ToolResult(
            success=False, output="", error=f"Unknown background task: {validated.task_id}"
        )
    killed = False
    if shell.process is not None and shell.process.returncode is None:
        shell.process.terminate()
        killed = True
    if shell.drain_task is not None:
        shell.drain_task.cancel()
    return ToolResult(
        success=True,
        output=f"已终止后台任务 {validated.task_id}" + ("（进程仍在清理中）" if not killed else ""),
        metadata={"terminated": True},
    )


_bash_config_ref: AppConfig | None = None


def _bash_max_output_chars() -> int:
    if _bash_config_ref is not None:
        return _bash_config_ref.agent.bash_max_output_chars
    return DEFAULT_BASH_MAX_OUTPUT_CHARS


def create_bash_tool(registry: ToolRegistry, config: AppConfig | None = None) -> None:
    global _bash_config_ref
    if config is not None:
        _bash_config_ref = config
    registry.register(
        ToolDefinition(
            name="bash",
            description=(
                "何时调用：只读诊断、运行测试、构建或代码检查；长时命令（开发服务器等）"
                "用 run_in_background=true 后台运行，再用 bash_output 读取输出。"
                "何时禁止：不要用于联网下载、安装依赖、删除/覆盖文件、git reset、推送、"
                "权限提升或任何破坏性命令。"
            ),
            parameters_model=BashParams,
            category="builtin",
            canonical_name="builtin.bash",
            risk_level="high",
            requires_approval=True,
        ),
        _bash_handler,
    )
    registry.register(
        ToolDefinition(
            name="bash_output",
            description="何时调用：读取后台 bash 任务的累计输出与运行状态。何时禁止：前台命令的输出直接随结果返回，不要使用。",
            parameters_model=BashOutputParams,
            category="builtin",
            canonical_name="builtin.bash_output",
            read_only=True,
            risk_level="low",
        ),
        _bash_output_handler,
    )
    registry.register(
        ToolDefinition(
            name="bash_kill",
            description="何时调用：终止一个后台 bash 任务。何时禁止：任务已自然结束或 task_id 无效时不要使用。",
            parameters_model=BashKillParams,
            category="builtin",
            canonical_name="builtin.bash_kill",
            risk_level="medium",
        ),
        _bash_kill_handler,
    )
