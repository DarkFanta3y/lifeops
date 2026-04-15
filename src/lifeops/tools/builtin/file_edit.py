from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from lifeops.tools.base import ToolDefinition, ToolParams, ToolResult
from lifeops.tools.registry import ToolRegistry
from lifeops.utils.logging import get_logger

logger = get_logger(__name__)


class FileEditParams(ToolParams):
    path: str
    operation: Literal["create", "replace", "append"]
    content: str | None = None
    old_text: str | None = None
    new_text: str | None = None


async def _file_edit_handler(params: dict[str, Any]) -> ToolResult:
    validated = FileEditParams.model_validate(params)
    file_path = validated.path
    operation = validated.operation

    try:
        path = Path(file_path)

        if operation == "create":
            path.parent.mkdir(parents=True, exist_ok=True)
            content = validated.content or ""
            path.write_text(content, encoding="utf-8")
            return ToolResult(success=True, output=f"Created {file_path}")

        elif operation == "replace":
            if not path.exists():
                return ToolResult(success=False, output="", error=f"File not found: {file_path}")
            if validated.old_text is None or validated.old_text == "":
                return ToolResult(
                    success=False, output="", error="old_text is required for replace operation"
                )
            old_text = validated.old_text
            new_text = validated.new_text or ""
            content = path.read_text(encoding="utf-8")
            if old_text not in content:
                return ToolResult(success=False, output="", error="Text not found in file")
            new_content = content.replace(old_text, new_text)
            path.write_text(new_content, encoding="utf-8")
            return ToolResult(success=True, output=f"Replaced in {file_path}")

        elif operation == "append":
            content = validated.content or ""
            if path.exists():
                existing = path.read_text(encoding="utf-8")
                if not existing.endswith("\n"):
                    content = "\n" + content
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(content)
            return ToolResult(success=True, output=f"Appended to {file_path}")

        else:
            return ToolResult(success=False, output="", error=f"Unknown operation: {operation}")
    except Exception as e:
        return ToolResult(success=False, output="", error=str(e))


def create_file_edit_tool(registry: ToolRegistry) -> None:
    definition = ToolDefinition(
        name="file_edit",
        description="Create, replace text, or append to files",
        parameters_model=FileEditParams,
        category="builtin",
    )
    registry.register(definition, _file_edit_handler)
