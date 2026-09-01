from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import Field

from lifeops.tools.base import ToolDefinition, ToolParams, ToolResult
from lifeops.tools.builtin.edit_guard import FileEditGuard
from lifeops.tools.registry import ToolRegistry
from lifeops.utils.logging import get_logger

logger = get_logger(__name__)


class FileReadParams(ToolParams):
    path: str = Field(
        min_length=1,
        pattern=r".+",
        description="要读取的文件路径，或要列出的目录路径",
    )
    encoding: str = Field(default="utf-8", min_length=1, description="读取文件时使用的编码")
    offset: int = Field(default=1, ge=1, description="从第几行开始读取，1 表示第一行")
    limit: int = Field(default=2000, ge=1, le=5000, description="最多返回的行数")


async def _file_read_handler(
    params: dict[str, Any], edit_guard: FileEditGuard | None = None
) -> ToolResult:
    validated = FileReadParams.model_validate(params)
    file_path = validated.path
    offset = validated.offset
    limit = validated.limit
    encoding = validated.encoding

    try:
        path = Path(file_path)
        if not path.exists():
            return ToolResult(success=False, output="", error=f"File not found: {file_path}")
        if path.is_dir():
            entries = sorted(path.iterdir())
            lines = [f"{e.name}{'/' if e.is_dir() else ''}" for e in entries]
            return ToolResult(success=True, output="\n".join(lines))

        text = path.read_text(encoding=encoding, errors="replace")
        if edit_guard is not None:
            edit_guard.mark_read(path)
        all_lines = text.splitlines()
        start = max(0, offset - 1)
        end = min(len(all_lines), start + limit)
        selected = all_lines[start:end]

        numbered = [f"{start + i + 1}: {line}" for i, line in enumerate(selected)]
        result_text = "\n".join(numbered)

        if end < len(all_lines):
            result_text += f"\n... ({len(all_lines) - end} more lines)"

        return ToolResult(
            success=True,
            output=result_text,
            metadata={"total_lines": len(all_lines), "shown_lines": end - start},
        )
    except Exception as e:
        return ToolResult(success=False, output="", error=str(e))


def create_file_read_tool(registry: ToolRegistry, edit_guard: FileEditGuard | None = None) -> None:
    async def handler(params: dict[str, Any]) -> ToolResult:
        return await _file_read_handler(params, edit_guard=edit_guard)

    definition = ToolDefinition(
        name="file_read",
        description=(
            "何时调用：读取文件内容或列出目录；编辑文件前必须先读取目标文件。"
            "何时禁止：不要用于创建、替换、追加或删除文件。"
        ),
        parameters_model=FileReadParams,
        category="builtin",
        canonical_name="builtin.file_read",
        read_only=True,
        risk_level="low",
    )
    registry.register(definition, handler)
