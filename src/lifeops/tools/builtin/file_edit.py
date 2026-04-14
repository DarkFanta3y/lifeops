from pathlib import Path

from lifeops.tools.base import ToolDefinition, ToolParameter, ToolResult
from lifeops.tools.registry import ToolRegistry
from lifeops.utils.logging import get_logger

logger = get_logger(__name__)


async def _file_edit_handler(params: dict) -> ToolResult:
    file_path = params["path"]
    operation = params.get("operation", "replace")

    try:
        path = Path(file_path)

        if operation == "create":
            path.parent.mkdir(parents=True, exist_ok=True)
            content = params.get("content", "")
            path.write_text(content, encoding="utf-8")
            return ToolResult(success=True, output=f"Created {file_path}")

        elif operation == "replace":
            if not path.exists():
                return ToolResult(success=False, output="", error=f"File not found: {file_path}")
            old_text = params.get("old_text", "")
            new_text = params.get("new_text", "")
            content = path.read_text(encoding="utf-8")
            if old_text not in content:
                return ToolResult(success=False, output="", error="Text not found in file")
            new_content = content.replace(old_text, new_text)
            path.write_text(new_content, encoding="utf-8")
            return ToolResult(success=True, output=f"Replaced in {file_path}")

        elif operation == "append":
            content = params.get("content", "")
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
        parameters=[
            ToolParameter(name="path", type="string", description="Path to the file", required=True),
            ToolParameter(name="operation", type="string", description="Operation: create, replace, or append", required=True),
            ToolParameter(name="content", type="string", description="Content to write (for create/append)", required=False),
            ToolParameter(name="old_text", type="string", description="Text to find (for replace)", required=False),
            ToolParameter(name="new_text", type="string", description="Replacement text (for replace)", required=False),
        ],
        category="builtin",
    )
    registry.register(definition, _file_edit_handler)