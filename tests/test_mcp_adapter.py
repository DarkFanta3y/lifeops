from __future__ import annotations

from unittest.mock import AsyncMock

from lifeops.tools.base import ToolDefinition, ToolResult
from lifeops.tools.mcp.adapter import MCPRegistryAdapter
from lifeops.tools.mcp.types import MCPToolInfo
from lifeops.tools.registry import ToolRegistry


def _make_tool_info(
    server_name: str = "github",
    original_name: str = "search_repositories",
    description: str = "搜索仓库",
    input_schema: dict | None = None,
) -> MCPToolInfo:
    if input_schema is None:
        input_schema = {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词"},
            },
            "required": ["query"],
        }
    return MCPToolInfo(
        server_name=server_name,
        original_name=original_name,
        description=description,
        input_schema=input_schema,
    )


def _make_mock_client(server_name: str = "github") -> AsyncMock:
    client = AsyncMock()
    client._server_name = server_name
    client.call_tool = AsyncMock(
        return_value=ToolResult(success=True, output='{"name": "lifeops"}')
    )
    return client


def test_register_single_tool():
    registry = ToolRegistry()
    client = _make_mock_client()
    adapter = MCPRegistryAdapter(registry, client)
    tool = _make_tool_info()

    registered = adapter.register_tools([tool])

    assert registered == ["mcp.github.search_repositories"]
    assert registry.get_definition("mcp.github.search_repositories") is not None
    defn = registry.get_definition("mcp.github.search_repositories")
    assert defn.category == "mcp"
    assert defn.description == "搜索仓库"


def test_register_multiple_tools():
    registry = ToolRegistry()
    client = _make_mock_client()
    adapter = MCPRegistryAdapter(registry, client)

    tools = [
        _make_tool_info(original_name="search_repositories"),
        _make_tool_info(original_name="get_file_contents"),
        _make_tool_info(original_name="create_issue"),
    ]

    registered = adapter.register_tools(tools)

    assert len(registered) == 3
    assert all(name.startswith("mcp.github.") for name in registered)


async def test_handler_calls_client_with_original_name():
    registry = ToolRegistry()
    client = _make_mock_client()
    adapter = MCPRegistryAdapter(registry, client)
    tool = _make_tool_info()

    adapter.register_tools([tool])

    result = await registry.execute("mcp.github.search_repositories", {"query": "lifeops"})

    assert result.success is True
    client.call_tool.assert_awaited_once_with("search_repositories", {"query": "lifeops"})


async def test_handler_propagates_error():
    registry = ToolRegistry()
    client = _make_mock_client()
    client.call_tool = AsyncMock(
        return_value=ToolResult(success=False, output="", error="工具调用失败")
    )
    adapter = MCPRegistryAdapter(registry, client)
    tool = _make_tool_info()

    adapter.register_tools([tool])

    result = await registry.execute("mcp.github.search_repositories", {"query": "test"})

    assert result.success is False
    assert result.error == "工具调用失败"


def test_register_skips_conflicting_local_tool():
    registry = ToolRegistry()

    local_handler = AsyncMock(return_value=ToolResult(success=True, output="local"))
    local_defn = ToolDefinition(
        name="mcp.github.search_repositories",
        description="本地工具",
        parameters_model=type("P", (object,), {}),
        category="builtin",
    )
    registry.register(local_defn, local_handler)

    client = _make_mock_client()
    adapter = MCPRegistryAdapter(registry, client)
    tool = _make_tool_info()

    registered = adapter.register_tools([tool])

    assert registered == []
    defn = registry.get_definition("mcp.github.search_repositories")
    assert defn.description == "本地工具"


def test_register_empty_list():
    registry = ToolRegistry()
    client = _make_mock_client()
    adapter = MCPRegistryAdapter(registry, client)

    registered = adapter.register_tools([])

    assert registered == []


def test_params_model_with_required_fields():
    registry = ToolRegistry()
    client = _make_mock_client()
    adapter = MCPRegistryAdapter(registry, client)
    tool = _make_tool_info(
        input_schema={
            "type": "object",
            "properties": {
                "owner": {"type": "string"},
                "repo": {"type": "string"},
                "branch": {"type": "string"},
            },
            "required": ["owner", "repo"],
        }
    )

    adapter.register_tools([tool])

    defn = registry.get_definition("mcp.github.search_repositories")
    model = defn.parameters_model

    validated = model.model_validate({"owner": "octocat", "repo": "hello-world"})
    assert validated.owner == "octocat"
    assert validated.repo == "hello-world"

    validated_with_optional = model.model_validate(
        {
            "owner": "octocat",
            "repo": "hello-world",
            "branch": "main",
        }
    )
    assert validated_with_optional.branch == "main"


def test_params_model_rejects_extra_fields():
    registry = ToolRegistry()
    client = _make_mock_client()
    adapter = MCPRegistryAdapter(registry, client)
    tool = _make_tool_info()

    adapter.register_tools([tool])

    defn = registry.get_definition("mcp.github.search_repositories")
    model = defn.parameters_model

    from pydantic import ValidationError

    try:
        model.model_validate({"query": "test", "unexpected": "field"})
        assert False, "应抛出 ValidationError"
    except ValidationError:
        pass


def test_params_model_no_properties():
    registry = ToolRegistry()
    client = _make_mock_client()
    adapter = MCPRegistryAdapter(registry, client)
    tool = _make_tool_info(input_schema={"type": "object"})

    adapter.register_tools([tool])

    defn = registry.get_definition("mcp.github.search_repositories")
    model = defn.parameters_model

    validated = model.model_validate({})
    assert validated is not None


async def test_unregister_tools():
    registry = ToolRegistry()
    client = _make_mock_client()
    adapter = MCPRegistryAdapter(registry, client)
    tools = [
        _make_tool_info(original_name="tool_a"),
        _make_tool_info(original_name="tool_b"),
    ]

    adapter.register_tools(tools)
    assert len(registry.list_definitions()) == 2

    adapter.unregister_tools(tools)
    assert len(registry.list_definitions()) == 0


async def test_unregister_nonexistent_tool():
    registry = ToolRegistry()
    client = _make_mock_client()
    adapter = MCPRegistryAdapter(registry, client)
    tool = _make_tool_info(original_name="nonexistent")

    adapter.unregister_tools([tool])
    assert len(registry.list_definitions()) == 0


def test_params_model_various_types():
    registry = ToolRegistry()
    client = _make_mock_client()
    adapter = MCPRegistryAdapter(registry, client)
    tool = _make_tool_info(
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "count": {"type": "integer"},
                "ratio": {"type": "number"},
                "enabled": {"type": "boolean"},
                "tags": {"type": "array"},
                "metadata": {"type": "object"},
            },
            "required": ["name", "count"],
        }
    )

    adapter.register_tools([tool])

    defn = registry.get_definition("mcp.github.search_repositories")
    model = defn.parameters_model

    validated = model.model_validate(
        {
            "name": "test",
            "count": 42,
            "ratio": 3.14,
            "enabled": True,
            "tags": ["a", "b"],
            "metadata": {"key": "val"},
        }
    )
    assert validated.name == "test"
    assert validated.count == 42
    assert validated.ratio == 3.14
    assert validated.enabled is True
    assert validated.tags == ["a", "b"]
    assert validated.metadata == {"key": "val"}


def test_register_tools_partial_conflict():
    registry = ToolRegistry()
    client = _make_mock_client()
    adapter = MCPRegistryAdapter(registry, client)

    tool_a = _make_tool_info(original_name="tool_a")
    adapter.register_tools([tool_a])

    tool_b = _make_tool_info(original_name="tool_b")
    tool_a_again = _make_tool_info(original_name="tool_a")
    registered = adapter.register_tools([tool_b, tool_a_again])

    assert "mcp.github.tool_b" in registered
    assert "mcp.github.tool_a" not in registered
    assert len(registered) == 1


async def test_end_to_end_register_execute_unregister():
    registry = ToolRegistry()
    client = _make_mock_client("github")
    adapter = MCPRegistryAdapter(registry, client)

    tools = [
        _make_tool_info(original_name="search", description="搜索"),
        _make_tool_info(
            original_name="create",
            description="创建",
            input_schema={
                "type": "object",
                "properties": {"title": {"type": "string"}, "body": {"type": "string"}},
                "required": ["title"],
            },
        ),
    ]

    registered = adapter.register_tools(tools)
    assert len(registered) == 2

    result = await registry.execute("mcp.github.search", {"query": "test"})
    assert result.success is True
    client.call_tool.assert_awaited_with("search", {"query": "test"})

    adapter.unregister_tools(tools)
    assert len(registry.list_definitions()) == 0

    try:
        await registry.execute("mcp.github.search", {"query": "test"})
        assert False, "应抛出 KeyError"
    except KeyError:
        pass
