import pytest
from pydantic import ValidationError

from lifeops.tools.base import ToolDefinition, ToolParams, ToolResult
from lifeops.tools.registry import ToolRegistry


class MockParams(ToolParams):
    command: str


def test_tool_definition_creation():
    tool_def = ToolDefinition(name="bash", description="Execute bash", parameters_model=MockParams)
    assert tool_def.name == "bash"
    assert tool_def.parameters_model is MockParams


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

    class CmdParams(ToolParams):
        cmd: str

    tool_def = ToolDefinition(name="bash", description="Execute bash", parameters_model=CmdParams)

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

    class EmptyParams(ToolParams):
        pass

    tool_def = ToolDefinition(name="bash", description="Execute bash", parameters_model=EmptyParams)
    registry.register(tool_def, _handler)

    tool_def2 = ToolDefinition(name="read", description="Read file", parameters_model=EmptyParams)
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

    class CmdParams(ToolParams):
        command: str

    tool_def = ToolDefinition(name="bash", description="Execute bash", parameters_model=CmdParams)

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

    class CmdParams(ToolParams):
        command: str

    tool_def = ToolDefinition(name="bash", description="Execute bash", parameters_model=CmdParams)

    async def mock_bash(params: dict) -> ToolResult:
        return ToolResult(success=True, output="ok")

    registry.register(tool_def, mock_bash)

    with pytest.raises(ValidationError):
        await registry.execute("bash", {})


def test_registry_get_openai_schemas():
    registry = ToolRegistry()

    class CmdParams(ToolParams):
        cmd: str

    tool_def = ToolDefinition(name="bash", description="Execute bash", parameters_model=CmdParams)

    async def _handler(p):
        return ToolResult(success=True, output="")

    registry.register(tool_def, _handler)

    schemas = registry.get_openai_tool_schemas()
    assert len(schemas) == 1
    assert schemas[0]["type"] == "function"
    assert schemas[0]["function"]["name"] == "bash"
    assert "cmd" in schemas[0]["function"]["parameters"]["properties"]
    assert "cmd" in schemas[0]["function"]["parameters"]["required"]
