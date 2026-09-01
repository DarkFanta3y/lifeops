from __future__ import annotations

import difflib
from pathlib import Path
from typing import Any

from pydantic import Field

from lifeops.tools.base import ToolDefinition, ToolParams, ToolResult
from lifeops.tools.builtin.edit_guard import FileEditGuard
from lifeops.tools.registry import ToolRegistry
from lifeops.utils.logging import get_logger

logger = get_logger(__name__)

PATH_PATTERN = r".+"

MAX_DIFF_CHARS = 4000


class FileCreateParams(ToolParams):
    path: str = Field(min_length=1, pattern=PATH_PATTERN, description="要创建的新文件路径")
    content: str = Field(min_length=1, description="要写入新文件的完整内容")


class FileReplaceParams(ToolParams):
    path: str = Field(min_length=1, pattern=PATH_PATTERN, description="要修改的文件路径")
    old_text: str = Field(min_length=1, description="文件中必须精确且唯一存在的旧文本")
    new_text: str = Field(description="替换后的新文本，可为空字符串")


class FileAppendParams(ToolParams):
    path: str = Field(min_length=1, pattern=PATH_PATTERN, description="要追加内容的文件路径")
    content: str = Field(min_length=1, description="追加到文件末尾的内容")


def _unified_diff(old_text: str, new_text: str, path: str) -> str:
    diff = difflib.unified_diff(
        old_text.splitlines(keepends=True),
        new_text.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
    )
    joined = "".join(diff)
    if len(joined) > MAX_DIFF_CHARS:
        keep = MAX_DIFF_CHARS // 2
        joined = (
            joined[:keep]
            + f"\n... [diff 超长，已截断 {len(joined) - MAX_DIFF_CHARS} 字符] ...\n"
            + joined[-keep:]
        )
    return joined


def _unread_file_error(path: str) -> ToolResult:
    return ToolResult(
        success=False,
        output="",
        error=(
            f"必须先用 file_read 读取 {path} 的当前内容后才能编辑；"
            "请先读取文件，基于真实内容提供 old_text。"
        ),
        metadata={"guard": "read_before_edit"},
    )


async def _file_create_handler(params: dict[str, Any]) -> ToolResult:
    validated = FileCreateParams.model_validate(params)
    path = Path(validated.path)
    if path.exists():
        return ToolResult(success=False, output="", error=f"File already exists: {validated.path}")

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(validated.content, encoding="utf-8")
        return ToolResult(
            success=True,
            output=f"Created {validated.path}",
            metadata={"diff": _unified_diff("", validated.content, validated.path)},
        )
    except Exception as e:
        return ToolResult(success=False, output="", error=str(e))


async def _file_replace_handler(
    params: dict[str, Any], edit_guard: FileEditGuard | None = None
) -> ToolResult:
    validated = FileReplaceParams.model_validate(params)
    path = Path(validated.path)
    if not path.exists():
        return ToolResult(success=False, output="", error=f"File not found: {validated.path}")
    if edit_guard is not None and not edit_guard.has_read(validated.path):
        return _unread_file_error(validated.path)

    try:
        content = path.read_text(encoding="utf-8")
        occurrences = content.count(validated.old_text)
        if occurrences == 0:
            return ToolResult(success=False, output="", error="Text not found in file")
        if occurrences > 1:
            return ToolResult(
                success=False,
                output="",
                error=(
                    f"old_text 在文件中出现 {occurrences} 次，无法确定替换位置；"
                    "请扩大 old_text 范围使其在文件中唯一。"
                ),
                metadata={"guard": "unique_old_text", "occurrences": occurrences},
            )
        new_content = content.replace(validated.old_text, validated.new_text)
        path.write_text(new_content, encoding="utf-8")
        return ToolResult(
            success=True,
            output=f"Replaced in {validated.path}",
            metadata={"diff": _unified_diff(content, new_content, validated.path)},
        )
    except Exception as e:
        return ToolResult(success=False, output="", error=str(e))


async def _file_append_handler(
    params: dict[str, Any], edit_guard: FileEditGuard | None = None
) -> ToolResult:
    validated = FileAppendParams.model_validate(params)
    path = Path(validated.path)
    if edit_guard is not None and path.exists() and not edit_guard.has_read(validated.path):
        return _unread_file_error(validated.path)

    try:
        content = validated.content
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        appended = content
        if existing and not existing.endswith("\n"):
            appended = "\n" + content
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(appended)
        return ToolResult(
            success=True,
            output=f"Appended to {validated.path}",
            metadata={"diff": _unified_diff(existing, existing + appended, validated.path)},
        )
    except Exception as e:
        return ToolResult(success=False, output="", error=str(e))


def create_simple_file_tools(
    registry: ToolRegistry, edit_guard: FileEditGuard | None = None
) -> None:
    async def file_replace_with_guard(params: dict[str, Any]) -> ToolResult:
        return await _file_replace_handler(params, edit_guard=edit_guard)

    async def file_append_with_guard(params: dict[str, Any]) -> ToolResult:
        return await _file_append_handler(params, edit_guard=edit_guard)

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
                "何时调用：把文件中一段精确且唯一的旧文本替换为新文本；编辑前必须先用 file_read 读过该文件。"
                "何时禁止：old_text 在文件中不唯一或未读取过文件时不要使用。"
            ),
            parameters_model=FileReplaceParams,
            category="builtin",
            canonical_name="builtin.file_replace",
            risk_level="high",
            requires_approval=True,
        ),
        file_replace_with_guard,
    )
    registry.register(
        ToolDefinition(
            name="file_append",
            description=(
                "何时调用：向已用 file_read 读过的文件末尾追加内容。"
                "何时禁止：需要覆盖或替换已有内容、或未读取过文件时不要使用。"
            ),
            parameters_model=FileAppendParams,
            category="builtin",
            canonical_name="builtin.file_append",
            risk_level="high",
            requires_approval=True,
        ),
        file_append_with_guard,
    )
