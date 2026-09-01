from __future__ import annotations

from lifeops.core.config import AppConfig
from lifeops.tools.builtin.bash import create_bash_tool
from lifeops.tools.builtin.edit_guard import FileEditGuard
from lifeops.tools.builtin.file_read import create_file_read_tool
from lifeops.tools.builtin.file_write import create_simple_file_tools
from lifeops.tools.builtin.search import create_search_tools
from lifeops.tools.builtin.web_search import create_web_search_tool
from lifeops.tools.registry import ToolRegistry


def register_all_builtin_tools(
    registry: ToolRegistry,
    config: AppConfig | None = None,
    edit_guard: FileEditGuard | None = None,
) -> None:
    create_bash_tool(registry, config)
    create_file_read_tool(registry, edit_guard=edit_guard)
    create_simple_file_tools(registry, edit_guard=edit_guard)
    create_search_tools(registry)
    create_web_search_tool(registry, config)
