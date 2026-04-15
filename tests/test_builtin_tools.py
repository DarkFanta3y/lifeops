import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from lifeops.core.config import AppConfig, SerpApiConfig
from lifeops.tools.builtin import register_all_builtin_tools
from lifeops.tools.builtin.web_search import WebSearchParams
from lifeops.tools.registry import ToolRegistry


@pytest.fixture
def registry():
    r = ToolRegistry()
    register_all_builtin_tools(r)
    return r


@pytest.fixture
def registry_empty_key():
    config = AppConfig(serpapi=SerpApiConfig(api_key=""))
    r = ToolRegistry()
    register_all_builtin_tools(r, config)
    return r


def test_register_all_builtin_tools(registry: ToolRegistry):
    tools = registry.list_definitions()
    names = {t.name for t in tools}
    assert "bash" in names
    assert "file_read" in names
    assert "file_edit" in names
    assert "web_search" in names


def test_register_without_config():
    r = ToolRegistry()
    register_all_builtin_tools(r)
    names = {t.name for t in r.list_definitions()}
    assert "web_search" in names


def test_register_with_config():
    r = ToolRegistry()
    register_all_builtin_tools(r, AppConfig(serpapi=SerpApiConfig(api_key="")))
    names = {t.name for t in r.list_definitions()}
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
    with pytest.raises(ValidationError):
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


# --- Web search tests ---


@pytest.mark.asyncio
async def test_web_search_no_api_key(registry: ToolRegistry):
    result = await registry.execute("web_search", {"query": "test"})
    assert result.success is False
    assert "SerpApi API key" in result.error


@pytest.mark.asyncio
async def test_web_search_empty_api_key(registry_empty_key: ToolRegistry):
    result = await registry_empty_key.execute("web_search", {"query": "test"})
    assert result.success is False
    assert "SerpApi API key" in result.error


def test_web_search_params_defaults():
    params = WebSearchParams(query="test")
    assert params.query == "test"
    assert params.num_results == 10
    assert params.location is None
    assert params.language == "zh-cn"


def test_web_search_params_custom():
    params = WebSearchParams(query="python", num_results=5, location="Beijing", language="en")
    assert params.query == "python"
    assert params.num_results == 5
    assert params.location == "Beijing"
    assert params.language == "en"


def test_web_search_params_validation():
    with pytest.raises(ValidationError):
        WebSearchParams(query="test", num_results=0)
    with pytest.raises(ValidationError):
        WebSearchParams(query="test", num_results=101)


def test_web_search_params_extra_forbidden():
    with pytest.raises(ValidationError):
        WebSearchParams(query="test", unknown_field="value")


def _make_registry_with_mocked_client(mock_results=None, side_effect=None):
    config = AppConfig(serpapi=SerpApiConfig(api_key="test-api-key"))
    with patch("lifeops.tools.builtin.web_search.serpapi.Client") as MockClient:
        mock_client = MagicMock()
        if side_effect:
            mock_client.search.side_effect = side_effect
        elif mock_results is not None:
            mock_client.search.return_value = mock_results
        MockClient.return_value = mock_client

        r = ToolRegistry()
        register_all_builtin_tools(r, config)
        return r


@pytest.mark.asyncio
async def test_web_search_with_api_key_success():
    mock_results = {
        "organic_results": [
            {
                "title": "Python 官网",
                "link": "https://python.org",
                "snippet": "Python 编程语言官网",
            },
            {
                "title": "Python 教程",
                "link": "https://docs.python.org/tutorial",
                "snippet": "学习 Python 的最佳资源",
            },
        ]
    }

    r = _make_registry_with_mocked_client(mock_results=mock_results)
    result = await r.execute("web_search", {"query": "python"})
    assert result.success is True
    assert "搜索结果" in result.output
    assert "Python 官网" in result.output
    assert "python.org" in result.output
    assert "Python 教程" in result.output


@pytest.mark.asyncio
async def test_web_search_with_api_key_no_results():
    r = _make_registry_with_mocked_client(mock_results={})
    result = await r.execute("web_search", {"query": "xyz"})
    assert result.success is True
    assert "未找到" in result.output


@pytest.mark.asyncio
async def test_web_search_api_key_error():
    import serpapi

    r = _make_registry_with_mocked_client(side_effect=serpapi.APIKeyNotProvided())
    result = await r.execute("web_search", {"query": "test"})
    assert result.success is False
    assert "SerpApi API key" in result.error


@pytest.mark.asyncio
async def test_web_search_timeout_error():
    import serpapi

    r = _make_registry_with_mocked_client(side_effect=serpapi.TimeoutError())
    result = await r.execute("web_search", {"query": "test"})
    assert result.success is False
    assert "超时" in result.error


@pytest.mark.asyncio
async def test_web_search_http_error():
    import requests
    import serpapi

    # HTTPError requires a requests.Response with status_code
    mock_response = MagicMock()
    mock_response.status_code = 429
    mock_response.json.return_value = {"error": "Rate limit exceeded"}
    mock_response.text = ""
    error = serpapi.HTTPError(requests.exceptions.HTTPError(response=mock_response))

    r = _make_registry_with_mocked_client(side_effect=error)
    result = await r.execute("web_search", {"query": "test"})
    assert result.success is False
    assert "搜索失败" in result.error
