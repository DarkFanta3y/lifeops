import os
import tempfile

import pytest

from lifeops.tools.builtin import register_all_builtin_tools
from lifeops.tools.registry import ToolRegistry


@pytest.fixture
def registry():
    r = ToolRegistry()
    register_all_builtin_tools(r)
    return r


def test_register_all_builtin_tools(registry: ToolRegistry):
    tools = registry.list_definitions()
    names = {t.name for t in tools}
    assert "bash" in names
    assert "file_read" in names
    assert "file_edit" in names
    assert "web_search" in names


@pytest.mark.asyncio
async def test_bash_tool(registry: ToolRegistry):
    result = await registry.execute("bash", {"command": "echo hello"})
    assert result.success is True
    assert "hello" in result.output


@pytest.mark.asyncio
async def test_bash_tool_with_error(registry: ToolRegistry):
    result = await registry.execute("bash", {"command": "ls /nonexistent_dir_12345"})
    assert result.success is False
    assert result.error is not None


@pytest.mark.asyncio
async def test_bash_tool_missing_param(registry: ToolRegistry):
    with pytest.raises(ValueError, match="Missing required parameter"):
        await registry.execute("bash", {})


@pytest.mark.asyncio
async def test_file_read_tool(registry: ToolRegistry):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("test content for reading")
        f.flush()
        path = f.name

    try:
        result = await registry.execute("file_read", {"path": path})
        assert result.success is True
        assert "test content for reading" in result.output
    finally:
        os.unlink(path)


@pytest.mark.asyncio
async def test_file_read_nonexistent(registry: ToolRegistry):
    result = await registry.execute("file_read", {"path": "/nonexistent_file_12345.txt"})
    assert result.success is False


@pytest.mark.asyncio
async def test_file_read_directory(registry: ToolRegistry):
    result = await registry.execute("file_read", {"path": "/tmp"})
    assert result.success is True


@pytest.mark.asyncio
async def test_file_edit_tool_create(registry: ToolRegistry):
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "test_edit.txt")
        result = await registry.execute(
            "file_edit",
            {"path": path, "operation": "create", "content": "hello world"},
        )
        assert result.success is True

        with open(path) as f:
            assert f.read() == "hello world"


@pytest.mark.asyncio
async def test_file_edit_tool_replace(registry: ToolRegistry):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("hello world")
        f.flush()
        path = f.name

    try:
        result = await registry.execute(
            "file_edit",
            {
                "path": path,
                "operation": "replace",
                "old_text": "hello",
                "new_text": "goodbye",
            },
        )
        assert result.success is True
        with open(path) as f:
            assert "goodbye world" == f.read()
    finally:
        os.unlink(path)


@pytest.mark.asyncio
async def test_web_search_placeholder(registry: ToolRegistry):
    result = await registry.execute("web_search", {"query": "test"})
    assert result.success is False
    assert "not yet implemented" in result.error