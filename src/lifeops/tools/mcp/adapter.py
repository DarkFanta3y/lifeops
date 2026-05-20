from __future__ import annotations

from typing import Any

from pydantic import create_model

from lifeops.tools.base import ToolDefinition, ToolHandler, ToolParams, ToolResult
from lifeops.tools.mcp.client import MCPClient
from lifeops.tools.mcp.types import MCPToolInfo, is_conflicting_name
from lifeops.tools.registry import ToolRegistry
from lifeops.utils.logging import get_logger

logger = get_logger(__name__)


class MCPRegistryAdapter:
    """将 MCP 工具映射到 ToolRegistry，处理参数校验与命名冲突。"""

    def __init__(self, registry: ToolRegistry, client: MCPClient) -> None:
        self._registry = registry
        self._client = client

    def register_tools(self, tools: list[MCPToolInfo]) -> list[str]:
        """将 MCP 工具列表注册到 ToolRegistry，返回成功注册的工具全名列表。

        跳过与本地工具冲突的工具（打印 warning）。
        """
        registered: list[str] = []

        for tool_info in tools:
            full_name = tool_info.full_name

            if is_conflicting_name(full_name, self._registry):
                logger.warning(f"跳过 MCP 工具 '{full_name}'：与已注册工具冲突")
                continue

            params_model = self._build_params_model(tool_info)
            handler = self._build_handler(tool_info)

            definition = ToolDefinition(
                name=full_name,
                description=tool_info.description,
                parameters_model=params_model,
                category="mcp",
                canonical_name=f"mcp.{tool_info.server_name}.{tool_info.original_name}",
                requires_approval=True,
            )

            self._registry.register(definition, handler)
            registered.append(full_name)

        return registered

    def unregister_tools(self, tools: list[MCPToolInfo]) -> None:
        """从 ToolRegistry 中移除 MCP 工具。"""
        for tool_info in tools:
            full_name = tool_info.full_name
            if full_name in self._registry._definitions:
                del self._registry._definitions[full_name]
                self._registry._handlers.pop(full_name, None)
            else:
                logger.warning(f"注销 MCP 工具 '{full_name}' 失败：未在注册中心找到")

    def _build_handler(self, tool_info: MCPToolInfo) -> ToolHandler:
        """为单个 MCP 工具构建 async handler。"""

        async def handler(params: dict[str, Any]) -> ToolResult:
            return await self._client.call_tool(tool_info.original_name, params)

        return handler

    def _build_params_model(self, tool_info: MCPToolInfo) -> type[ToolParams]:
        """基于 MCP input_schema 动态创建 ToolParams 子类。

        将 JSON Schema properties 转换为 pydantic 字段定义。
        """
        schema = tool_info.input_schema
        properties = schema.get("properties", {})
        required_fields = set(schema.get("required", []))

        if not properties:
            # 无参数工具，直接返回 ToolParams 子类
            model_name = f"MCPParams_{tool_info.server_name}_{tool_info.original_name}"
            return type(model_name, (ToolParams,), {"model_config": {"extra": "forbid"}})

        field_definitions: dict[str, Any] = {}
        for prop_name, prop_schema in properties.items():
            python_type = _json_schema_type_to_python(prop_schema)
            has_default = prop_name not in required_fields

            if has_default:
                # 非必填字段，默认值为 None
                field_definitions[prop_name] = (python_type | None, None)
            else:
                field_definitions[prop_name] = (python_type, ...)

        model_name = f"MCPParams_{tool_info.server_name}_{tool_info.original_name}"
        return create_model(
            model_name,
            __base__=ToolParams,
            **field_definitions,
        )


def _json_schema_type_to_python(schema: dict[str, Any]) -> type:
    """将 JSON Schema 类型映射为 Python 类型。"""
    json_type = schema.get("type", "string")

    type_map: dict[str, type] = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "array": list,
        "object": dict,
    }

    return type_map.get(json_type, str)
