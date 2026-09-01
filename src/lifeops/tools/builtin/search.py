from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path
from typing import Any

from pydantic import Field

from lifeops.tools.base import ToolDefinition, ToolParams, ToolResult
from lifeops.tools.registry import ToolRegistry
from lifeops.utils.logging import get_logger

logger = get_logger(__name__)

EXCLUDED_DIR_NAMES = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".lifeops",
    ".playwright-mcp",
    ".codex",
}

MAX_SCAN_FILES = 5000
MAX_GREP_OUTPUT_CHARS = 20000
MAX_GLOB_RESULTS = 200
BINARY_SNIFF_BYTES = 1024


class GrepParams(ToolParams):
    pattern: str = Field(min_length=1, description="要搜索的正则表达式")
    path: str = Field(default=".", description="搜索的起始目录或单个文件路径")
    glob: str | None = Field(
        default=None,
        description="可选的文件名过滤模式，如 '*.py'；仅匹配文件名，不匹配目录",
    )
    ignore_case: bool = Field(default=False, description="忽略大小写匹配")
    context_lines: int = Field(
        default=0, ge=0, le=2, description="每个匹配行前后展示的上下文行数"
    )
    max_results: int = Field(default=50, ge=1, le=200, description="最多返回的匹配行数")


class GlobParams(ToolParams):
    pattern: str = Field(min_length=1, description="文件匹配模式，如 'src/**/*.py' 或 '*.md'")
    path: str = Field(default=".", description="搜索的起始目录")


def _is_binary_file(path: Path) -> bool:
    try:
        head = path.open("rb").read(BINARY_SNIFF_BYTES)
    except OSError:
        return True
    return b"\x00" in head


def _iter_files(root: Path, filename_glob: str | None) -> list[Path]:
    files: list[Path] = []
    if root.is_file():
        return [root] if not filename_glob or fnmatch.fnmatch(root.name, filename_glob) else []
    for current_dir, dir_names, file_names in os.walk(root):
        dir_names[:] = sorted(d for d in dir_names if d not in EXCLUDED_DIR_NAMES)
        for file_name in sorted(file_names):
            if filename_glob and not fnmatch.fnmatch(file_name, filename_glob):
                continue
            files.append(Path(current_dir) / file_name)
            if len(files) >= MAX_SCAN_FILES:
                logger.warning(f"grep/glob 遍历文件数达到上限 {MAX_SCAN_FILES}，提前停止")
                return files
    return files


def _truncate_output(output: str, limit: int) -> tuple[str, bool]:
    if len(output) <= limit:
        return output, False
    keep = limit // 2
    truncated = output[:keep] + f"\n... [输出超长，已截断 {len(output) - limit} 字符] ...\n" + output[-keep:]
    return truncated, True


async def _grep_handler(params: dict[str, Any]) -> ToolResult:
    validated = GrepParams.model_validate(params)
    try:
        flags = re.IGNORECASE if validated.ignore_case else 0
        regex = re.compile(validated.pattern, flags)
    except re.error as error:
        return ToolResult(success=False, output="", error=f"无效的正则表达式: {error}")

    root = Path(validated.path).expanduser()
    if not root.exists():
        return ToolResult(success=False, output="", error=f"路径不存在: {validated.path}")

    files = _iter_files(root, validated.glob)
    matches: list[str] = []
    total_matches = 0
    scanned_files = 0

    for file_path in files:
        if _is_binary_file(file_path):
            continue
        scanned_files += 1
        try:
            text = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lines = text.splitlines()
        base = _relative_label(root, file_path)
        for line_no, line in enumerate(lines, start=1):
            if not regex.search(line):
                continue
            total_matches += 1
            if len(matches) >= validated.max_results:
                continue
            if validated.context_lines:
                start = max(0, line_no - 1 - validated.context_lines)
                end = min(len(lines), line_no + validated.context_lines)
                matches.append(
                    "\n".join(f"{base}:{n}: {lines[n - 1]}" for n in range(start + 1, end + 1))
                )
            else:
                matches.append(f"{base}:{line_no}: {line}")

    if not matches:
        return ToolResult(
            success=True,
            output=f"未找到匹配（扫描 {scanned_files} 个文件）",
            metadata={"total_matches": 0, "scanned_files": scanned_files},
        )

    output, truncated = _truncate_output("\n\n".join(matches), MAX_GREP_OUTPUT_CHARS)
    return ToolResult(
        success=True,
        output=output,
        metadata={
            "total_matches": total_matches,
            "returned_matches": min(len(matches), validated.max_results),
            "scanned_files": scanned_files,
            "truncated": truncated,
            "hit_limit": total_matches > len(matches),
        },
    )


def _relative_label(root: Path, file_path: Path) -> str:
    if root.is_file():
        return root.name
    try:
        return str(file_path.relative_to(root))
    except ValueError:
        return str(file_path)


async def _glob_handler(params: dict[str, Any]) -> ToolResult:
    validated = GlobParams.model_validate(params)
    root = Path(validated.path).expanduser()
    if not root.exists():
        return ToolResult(success=False, output="", error=f"路径不存在: {validated.path}")
    if not root.is_dir():
        return ToolResult(success=False, output="", error=f"路径不是目录: {validated.path}")

    try:
        candidates = sorted(root.glob(validated.pattern))
    except (ValueError, NotImplementedError) as error:
        return ToolResult(success=False, output="", error=f"无效的匹配模式: {error}")

    results: list[str] = []
    for candidate in candidates:
        if not candidate.is_file():
            continue
        parts = candidate.relative_to(root).parts
        if any(part in EXCLUDED_DIR_NAMES for part in parts[:-1]):
            continue
        results.append(candidate.relative_to(root).as_posix())
        if len(results) >= MAX_GLOB_RESULTS:
            break

    if not results:
        return ToolResult(success=True, output="未找到匹配文件", metadata={"count": 0})
    output = "\n".join(results)
    return ToolResult(
        success=True,
        output=output,
        metadata={"count": len(results), "hit_limit": len(results) >= MAX_GLOB_RESULTS},
    )


def create_search_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolDefinition(
            name="grep",
            description=(
                "何时调用：在文件内容中按正则搜索匹配行，定位代码、配置或文本。"
                "何时禁止：不要用于列文件名（用 glob）或读取整个文件（用 file_read）。"
            ),
            parameters_model=GrepParams,
            category="builtin",
            canonical_name="builtin.grep",
            read_only=True,
            risk_level="low",
        ),
        _grep_handler,
    )
    registry.register(
        ToolDefinition(
            name="glob",
            description=(
                "何时调用：按模式查找文件路径，如 'src/**/*.py'。"
                "何时禁止：需要搜索文件内容时用 grep，不要用 glob。"
            ),
            parameters_model=GlobParams,
            category="builtin",
            canonical_name="builtin.glob",
            read_only=True,
            risk_level="low",
        ),
        _glob_handler,
    )
