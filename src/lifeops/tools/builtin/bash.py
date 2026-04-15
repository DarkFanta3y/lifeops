from __future__ import annotations

import asyncio
from typing import Any

from lifeops.tools.base import ToolDefinition, ToolParams, ToolResult
from lifeops.tools.registry import ToolRegistry
from lifeops.utils.logging import get_logger

logger = get_logger(__name__)


class BashParams(ToolParams):
    command: str
    timeout: int = 30
    workdir: str | None = None


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
        description="Execute a bash command and return the output",
        parameters_model=BashParams,
        category="builtin",
    )
    registry.register(definition, _bash_handler)
