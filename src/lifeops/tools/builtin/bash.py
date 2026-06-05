from __future__ import annotations

import asyncio
from typing import Any

from pydantic import Field

from lifeops.tools.base import ToolDefinition, ToolParams, ToolResult
from lifeops.tools.registry import ToolRegistry
from lifeops.utils.logging import get_logger

logger = get_logger(__name__)


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


async def _bash_handler(params: dict[str, Any]) -> ToolResult:
    validated = BashParams.model_validate(params)
    command = validated.command
    timeout = validated.timeout
    workdir = validated.workdir

    try:
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=workdir,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        output = stdout.decode("utf-8", errors="replace")
        error_output = stderr.decode("utf-8", errors="replace")

        if process.returncode == 0:
            return ToolResult(success=True, output=output or "(no output)")
        else:
            return ToolResult(
                success=False,
                output=output,
                error=f"Exit code {process.returncode}: {error_output}",
            )
    except asyncio.TimeoutError:
        return ToolResult(success=False, output="", error=f"Command timed out after {timeout}s")
    except Exception as e:
        return ToolResult(success=False, output="", error=str(e))


def create_bash_tool(registry: ToolRegistry) -> None:
    definition = ToolDefinition(
        name="bash",
        description=(
            "何时调用：只读诊断、运行测试、构建或代码检查。何时禁止：不要用于联网下载、安装依赖、"
            "删除/覆盖文件、git reset、推送、权限提升或任何破坏性命令。"
        ),
        parameters_model=BashParams,
        category="builtin",
        canonical_name="builtin.bash",
        risk_level="high",
        requires_approval=True,
    )
    registry.register(definition, _bash_handler)
