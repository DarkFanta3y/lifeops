from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import Field

from lifeops.tools.base import ToolDefinition, ToolParams, ToolResult
from lifeops.tools.registry import ToolRegistry
from lifeops.utils.logging import get_logger

logger = get_logger(__name__)

PATH_PATTERN = r".+"


class FileCreateParams(ToolParams):
    path: str = Field(min_length=1, pattern=PATH_PATTERN, description="要创建的新文件路径")
    content: str = Field(min_length=1, description="要写入新文件的完整内容")


class FileReplaceParams(ToolParams):
    path: str = Field(min_length=1, pattern=PATH_PATTERN, description="要修改的文件路径")
    old_text: str = Field(min_length=1, description="文件中必须精确存在的旧文本")
    new_text: str = Field(description="替换后的新文本，可为空字符串")


class FileAppendParams(ToolParams):
    path: str = Field(min_length=1, pattern=PATH_PATTERN, description="要追加内容的文件路径")
    content: str = Field(min_length=1, description="追加到文件末尾的内容")


async def _file_create_handler(params: dict[str, Any]) -> ToolResult:
    validated = FileCreateParams.model_validate(params)
    path = Path(validated.path)
    if path.exists():
        return ToolResult(success=False, output="", error=f"File already exists: {validated.path}")

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(validated.content, encoding="utf-8")
        return ToolResult(success=True, output=f"Created {validated.path}")
    except Exception as e:
        return ToolResult(success=False, output="", error=str(e))


async def _file_replace_handler(params: dict[str, Any]) -> ToolResult:
    validated = FileReplaceParams.model_validate(params)
    path = Path(validated.path)
    if not path.exists():
        return ToolResult(success=False, output="", error=f"File not found: {validated.path}")

    try:
        content = path.read_text(encoding="utf-8")
        if validated.old_text not in content:
            return ToolResult(success=False, output="", error="Text not found in file")
        path.write_text(content.replace(validated.old_text, validated.new_text), encoding="utf-8")
        return ToolResult(success=True, output=f"Replaced in {validated.path}")
    except Exception as e:
        return ToolResult(success=False, output="", error=str(e))


async def _file_append_handler(params: dict[str, Any]) -> ToolResult:
    validated = FileAppendParams.model_validate(params)
    path = Path(validated.path)

    try:
        content = validated.content
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        if existing and not existing.endswith("\n"):
            content = "\n" + content
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(content)
        return ToolResult(success=True, output=f"Appended to {validated.path}")
    except Exception as e:
        return ToolResult(success=False, output="", error=str(e))


def create_simple_file_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolDefinition(
            name="file_create",
            description=(
                "何时调用：创建一个当前不存在的新文件。何时禁止：目标文件已存在、需要替换或追加时不要使用。"
            ),
            parameters_model=FileCreateParams,
            category="builtin",
            canonical_name="builtin.file_create",
            risk_level="high",
            requires_approval=True,
        ),
        _file_create_handler,
    )
    registry.register(
        ToolDefinition(
            name="file_replace",
            description=(
                "何时调用：把文件中的一段精确旧文本替换为新文本。何时禁止：无法提供唯一 old_text 时不要使用。"
            ),
            parameters_model=FileReplaceParams,
            category="builtin",
            canonical_name="builtin.file_replace",
            risk_level="high",
            requires_approval=True,
        ),
        _file_replace_handler,
    )
    registry.register(
        ToolDefinition(
            name="file_append",
            description="何时调用：向文件末尾追加内容。何时禁止：需要覆盖或替换已有内容时不要使用。",
            parameters_model=FileAppendParams,
            category="builtin",
            canonical_name="builtin.file_append",
            risk_level="high",
            requires_approval=True,
        ),
        _file_append_handler,
    )
