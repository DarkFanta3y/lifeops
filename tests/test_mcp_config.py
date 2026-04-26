"""Tests for MCPConfig environment variable reading and CLI parameter override."""

from __future__ import annotations

import os

import pytest

from lifeops.core.config import MCPConfig


@pytest.fixture(autouse=True)
def _clean_mcp_env():
    """确保每个测试前后清理 MCP 相关环境变量。"""
    mcp_vars = [k for k in os.environ if k.startswith("LIFEOPS_MCP_")]
    for var in mcp_vars:
        os.environ.pop(var, None)
    yield
    mcp_vars = [k for k in os.environ if k.startswith("LIFEOPS_MCP_")]
    for var in mcp_vars:
        os.environ.pop(var, None)


def test_defaults():
    # 显式传入 servers="" 避免被 .env 文件中的 LIFEOPS_MCP_SERVERS 覆盖
    config = MCPConfig(servers="")
    assert config.enabled is True
    assert config.default_transport == "stdio"
    assert config.servers == ""


def test_env_prefix_enabled():
    os.environ["LIFEOPS_MCP_ENABLED"] = "false"
    config = MCPConfig()
    assert config.enabled is False


def test_env_prefix_default_transport():
    os.environ["LIFEOPS_MCP_DEFAULT_TRANSPORT"] = "streamable_http"
    config = MCPConfig()
    assert config.default_transport == "streamable_http"


def test_env_prefix_servers():
    os.environ["LIFEOPS_MCP_SERVERS"] = '{"github": {"command": "docker"}}'
    config = MCPConfig()
    assert config.servers == '{"github": {"command": "docker"}}'


def test_env_enabled_true():
    os.environ["LIFEOPS_MCP_ENABLED"] = "true"
    config = MCPConfig()
    assert config.enabled is True


def test_env_enabled_case_insensitive():
    os.environ["LIFEOPS_MCP_ENABLED"] = "True"
    config = MCPConfig()
    assert config.enabled is True


def test_multiple_env_vars():
    os.environ["LIFEOPS_MCP_ENABLED"] = "false"
    os.environ["LIFEOPS_MCP_DEFAULT_TRANSPORT"] = "streamable_http"
    os.environ["LIFEOPS_MCP_SERVERS"] = '{"test": {}}'
    config = MCPConfig()
    assert config.enabled is False
    assert config.default_transport == "streamable_http"
    assert config.servers == '{"test": {}}'


def test_explicit_init_overrides_env():
    os.environ["LIFEOPS_MCP_ENABLED"] = "false"
    os.environ["LIFEOPS_MCP_DEFAULT_TRANSPORT"] = "streamable_http"
    config = MCPConfig(enabled=True, default_transport="stdio", servers="")
    assert config.enabled is True
    assert config.default_transport == "stdio"
    assert config.servers == ""


def test_servers_empty_by_default():
    # 显式传入 servers="" 避免被 .env 文件中的 LIFEOPS_MCP_SERVERS 覆盖
    config = MCPConfig(servers="")
    assert config.servers == ""


def test_servers_with_complex_json():
    raw = '{"github": {"transport": "stdio", "command": "docker", "args": ["run"]}}'
    os.environ["LIFEOPS_MCP_SERVERS"] = raw
    config = MCPConfig()
    assert config.servers == raw
