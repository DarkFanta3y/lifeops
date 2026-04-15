from __future__ import annotations

from typing import Any

from lifeops.tools.base import ToolDefinition, ToolParams, ToolResult
from lifeops.tools.registry import ToolRegistry
from lifeops.utils.logging import get_logger

logger = get_logger(__name__)


class WebSearchParams(ToolParams):
    query: str


async def _web_search_handler(params: dict[str, Any]) -> ToolResult:
    validated = WebSearchParams.model_validate(params)
    logger.info(f"Web search requested: {validated.query}")
    return ToolResult(
        success=False,
        output="",
        error="Web search not yet implemented. Install a search provider MCP server.",
    )


def create_web_search_tool(registry: ToolRegistry) -> None:
    definition = ToolDefinition(
        name="web_search",
        description="Search the web for information (requires MCP search server)",
        parameters_model=WebSearchParams,
        category="builtin",
    )
    registry.register(definition, _web_search_handler)
