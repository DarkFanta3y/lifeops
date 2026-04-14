from lifeops.tools.base import ToolDefinition, ToolParameter, ToolResult
from lifeops.tools.registry import ToolRegistry
from lifeops.utils.logging import get_logger

logger = get_logger(__name__)


async def _web_search_handler(params: dict) -> ToolResult:
    query = params["query"]
    logger.info(f"Web search requested: {query}")
    return ToolResult(
        success=False,
        output="",
        error="Web search not yet implemented. Install a search provider MCP server.",
    )


def create_web_search_tool(registry: ToolRegistry) -> None:
    definition = ToolDefinition(
        name="web_search",
        description="Search the web for information (requires MCP search server)",
        parameters=[
            ToolParameter(name="query", type="string", description="Search query", required=True),
        ],
        category="builtin",
    )
    registry.register(definition, _web_search_handler)