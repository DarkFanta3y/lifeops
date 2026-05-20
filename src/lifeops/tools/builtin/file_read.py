from __future__ import annotations

from pathlib import Path
from typing import Any

from lifeops.tools.base import ToolDefinition, ToolParams, ToolResult
from lifeops.tools.registry import ToolRegistry
from lifeops.utils.logging import get_logger

logger = get_logger(__name__)


class FileReadParams(ToolParams):
    path: str
    encoding: str = "utf-8"
    offset: int = 1
    limit: int = 2000


async def _file_read_handler(params: dict[str, Any]) -> ToolResult:
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


def create_file_read_tool(registry: ToolRegistry) -> None:
    definition = ToolDefinition(
        name="file_read",
        description="Read a file or list a directory",
        parameters_model=FileReadParams,
        category="builtin",
        canonical_name="builtin.file_read",
        read_only=True,
        risk_level="low",
    )
    registry.register(definition, _file_read_handler)
