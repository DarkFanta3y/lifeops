from __future__ import annotations

from typing import Any

from lifeops.tools.base import ToolDefinition, ToolHandler, ToolResult
from lifeops.utils.logging import get_logger

logger = get_logger(__name__)


class ToolRegistry:
    def __init__(self):
        self._definitions: dict[str, ToolDefinition] = {}
        self._handlers: dict[str, ToolHandler] = {}

    def register(self, definition: ToolDefinition, handler: ToolHandler) -> None:
        name = definition.name
        if name in self._definitions:
            logger.warning(f"Tool '{name}' already registered, overwriting")
        self._definitions[name] = definition
        self._handlers[name] = handler

    def get_definition(self, name: str) -> ToolDefinition | None:
        return self._definitions.get(name)

    def get_handler(self, name: str) -> ToolHandler | None:
        return self._handlers.get(name)

    def list_definitions(self) -> list[ToolDefinition]:
        return list(self._definitions.values())

    async def execute(self, name: str, params: dict[str, Any]) -> ToolResult:
        handler = self._handlers.get(name)
        if handler is None:
            raise KeyError(f"Tool '{name}' not found in registry")

        definition = self._definitions[name]
        logger.info(f"Executing tool: {name}")

        self._validate_params(definition, params)

        try:
            result = await handler(params)
            logger.info(f"Tool '{name}' completed: success={result.success}")
            return result
        except Exception as e:
            logger.error(f"Tool '{name}' failed: {e}")
            return ToolResult(success=False, output="", error=str(e))

    def _validate_params(self, definition: ToolDefinition, params: dict[str, Any]) -> None:
        definition.parameters_model.model_validate(params)

    def get_openai_tool_schemas(self) -> list[dict]:
        schemas = []
        for tool_def in self._definitions.values():
            json_schema = tool_def.parameters_model.model_json_schema()
            parameters = {
                "type": "object",
                "properties": json_schema.get("properties", {}),
                "required": json_schema.get("required", []),
            }
            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool_def.name,
                        "description": tool_def.description,
                        "parameters": parameters,
                    },
                }
            )
        return schemas
