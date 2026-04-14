import pytest

from lifeops.tools.base import ToolDefinition, ToolParameter, ToolResult
from lifeops.tools.registry import ToolRegistry


def test_tool_definition_creation():
    param = ToolParameter(name="command", type="string", description="cmd", required=True)
    tool_def = ToolDefinition(name="bash", description="Execute bash", parameters=[param])
    assert tool_def.name == "bash"
    assert len(tool_def.parameters) == 1


def test_tool_result_success():
    result = ToolResult(success=True, output="file1\nfile2")
    assert result.success is True
    assert result.output == "file1\nfile2"


def test_tool_result_failure():
    result = ToolResult(success=False, output="", error="Command not found")
    assert result.success is False
    assert result.error == "Command not found"


def test_registry_register_and_get():
    registry = ToolRegistry()
    param = ToolParameter(name="cmd", type="string", description="command", required=True)
    tool_def = ToolDefinition(name="bash", description="Execute bash", parameters=[param])

    async def bash_handler(params: dict) -> ToolResult:
        return ToolResult(success=True, output="ok")

    registry.register(tool_def, bash_handler)

    retrieved = registry.get_definition("bash")
    assert retrieved is not None
    assert retrieved.name == "bash"

    handler = registry.get_handler("bash")
    assert handler is not None


def test_registry_list_tools():
    registry = ToolRegistry()

    async def _handler(p):
        return ToolResult(success=True, output="")

    tool_def = ToolDefinition(name="bash", description="Execute bash", parameters=[])
    registry.register(tool_def, _handler)

    tool_def2 = ToolDefinition(name="read", description="Read file", parameters=[])
    registry.register(tool_def2, _handler)

    tools = registry.list_definitions()
    assert len(tools) == 2
    names = {t.name for t in tools}
    assert names == {"bash", "read"}


def test_registry_get_nonexistent():
    registry = ToolRegistry()
    assert registry.get_definition("nonexistent") is None
    assert registry.get_handler("nonexistent") is None


@pytest.mark.asyncio
async def test_registry_execute_tool():
    registry = ToolRegistry()
    param = ToolParameter(name="command", type="string", description="cmd", required=True)
    tool_def = ToolDefinition(name="bash", description="Execute bash", parameters=[param])

    async def mock_bash(params: dict) -> ToolResult:
        return ToolResult(success=True, output=f"ran: {params['command']}")

    registry.register(tool_def, mock_bash)

    result = await registry.execute("bash", {"command": "ls"})
    assert result.success is True
    assert "ran: ls" in result.output


@pytest.mark.asyncio
async def test_registry_execute_nonexistent_tool():
    registry = ToolRegistry()
    with pytest.raises(KeyError):
        await registry.execute("nonexistent", {})


@pytest.mark.asyncio
async def test_registry_execute_missing_required_param():
    registry = ToolRegistry()
    param = ToolParameter(name="command", type="string", description="cmd", required=True)
    tool_def = ToolDefinition(name="bash", description="Execute bash", parameters=[param])

    async def mock_bash(params: dict) -> ToolResult:
        return ToolResult(success=True, output="ok")

    registry.register(tool_def, mock_bash)

    with pytest.raises(ValueError, match="Missing required parameter"):
        await registry.execute("bash", {})


def test_registry_get_openai_schemas():
    registry = ToolRegistry()
    param = ToolParameter(name="cmd", type="string", description="command", required=True)
    tool_def = ToolDefinition(name="bash", description="Execute bash", parameters=[param])
    async def _handler(p):
        return ToolResult(success=True, output="")

    registry.register(tool_def, _handler)

    schemas = registry.get_openai_tool_schemas()
    assert len(schemas) == 1
    assert schemas[0]["type"] == "function"
    assert schemas[0]["function"]["name"] == "bash"
    assert "cmd" in schemas[0]["function"]["parameters"]["properties"]