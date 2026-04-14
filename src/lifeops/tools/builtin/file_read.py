from pathlib import Path

from lifeops.tools.base import ToolDefinition, ToolParameter, ToolResult
from lifeops.tools.registry import ToolRegistry
from lifeops.utils.logging import get_logger

logger = get_logger(__name__)


async def _file_read_handler(params: dict) -> ToolResult:
    file_path = params["path"]
    offset = params.get("offset", 1)
    limit = params.get("limit", 2000)

    try:
        path = Path(file_path)
        if not path.exists():
            return ToolResult(success=False, output="", error=f"File not found: {file_path}")
        if path.is_dir():
            entries = sorted(path.iterdir())
            lines = [f"{e.name}{'/' if e.is_dir() else ''}" for e in entries]
            return ToolResult(success=True, output="\n".join(lines))

        text = path.read_text(encoding="utf-8", errors="replace")
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
        parameters=[
            ToolParameter(name="path", type="string", description="Path to file or directory", required=True),
            ToolParameter(name="offset", type="integer", description="Line number to start reading from (1-indexed)", required=False),
            ToolParameter(name="limit", type="integer", description="Maximum number of lines to read", required=False),
        ],
        category="builtin",
    )
    registry.register(definition, _file_read_handler)