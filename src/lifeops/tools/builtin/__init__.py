from lifeops.tools.builtin.bash import create_bash_tool
from lifeops.tools.builtin.file_read import create_file_read_tool
from lifeops.tools.builtin.file_edit import create_file_edit_tool
from lifeops.tools.builtin.web_search import create_web_search_tool
from lifeops.tools.registry import ToolRegistry


def register_all_builtin_tools(registry: ToolRegistry) -> None:
    create_bash_tool(registry)
    create_file_read_tool(registry)
    create_file_edit_tool(registry)
    create_web_search_tool(registry)