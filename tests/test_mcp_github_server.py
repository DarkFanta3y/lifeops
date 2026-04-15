"""Tests for GitHub MCP Server configuration creation."""

from __future__ import annotations

import os

import pytest

from lifeops.tools.mcp.servers.github import (
    GITHUB_MCP_SERVER_IMAGE,
    OPTIONAL_ENV_VARS,
    REQUIRED_ENV_VARS,
    create_github_mcp_config,
    get_github_mcp_server_name,
)


@pytest.fixture(autouse=True)
def _clean_github_env():
    """清理所有 GitHub 相关环境变量。"""
    github_vars = ["GITHUB_PERSONAL_ACCESS_TOKEN"] + OPTIONAL_ENV_VARS
    saved = {}
    for var in github_vars:
        if var in os.environ:
            saved[var] = os.environ.pop(var)
    yield
    for var in github_vars:
        os.environ.pop(var, None)
    for var, val in saved.items():
        os.environ[var] = val


def test_create_config_with_token():
    os.environ["GITHUB_PERSONAL_ACCESS_TOKEN"] = "ghp_test123"
    config = create_github_mcp_config()

    assert config.transport == "stdio"
    assert config.command == "docker"
    assert config.args == ["run", "-i", "--rm", GITHUB_MCP_SERVER_IMAGE]
    assert config.env["GITHUB_PERSONAL_ACCESS_TOKEN"] == "ghp_test123"


def test_create_config_without_token_raises():
    os.environ.pop("GITHUB_PERSONAL_ACCESS_TOKEN", None)
    with pytest.raises(ValueError, match="GITHUB_PERSONAL_ACCESS_TOKEN"):
        create_github_mcp_config()


def test_create_config_token_empty_string_raises():
    os.environ["GITHUB_PERSONAL_ACCESS_TOKEN"] = ""
    with pytest.raises(ValueError, match="GITHUB_PERSONAL_ACCESS_TOKEN"):
        create_github_mcp_config()


def test_create_config_includes_optional_env_vars():
    os.environ["GITHUB_PERSONAL_ACCESS_TOKEN"] = "ghp_test"
    os.environ["GITHUB_TOOLSETS"] = "repos,issues"
    os.environ["GITHUB_READ_ONLY"] = "1"

    config = create_github_mcp_config()

    assert config.env["GITHUB_TOOLSETS"] == "repos,issues"
    assert config.env["GITHUB_READ_ONLY"] == "1"


def test_create_config_omits_unset_optional_vars():
    os.environ["GITHUB_PERSONAL_ACCESS_TOKEN"] = "ghp_test"

    config = create_github_mcp_config()

    assert "GITHUB_TOOLSETS" not in config.env
    assert "GITHUB_TOOLS" not in config.env
    assert "GITHUB_READ_ONLY" not in config.env
    assert "GITHUB_LOCKDOWN_MODE" not in config.env
    assert "GITHUB_INSIDERS" not in config.env
    assert "GITHUB_HOST" not in config.env


def test_create_config_optional_vars_none_not_included():
    os.environ["GITHUB_PERSONAL_ACCESS_TOKEN"] = "ghp_test"
    os.environ["GITHUB_HOST"] = "github.example.com"

    config = create_github_mcp_config()

    assert config.env["GITHUB_HOST"] == "github.example.com"
    assert "GITHUB_TOOLSETS" not in config.env


def test_docker_image_constant():
    assert GITHUB_MCP_SERVER_IMAGE == "ghcr.io/github/github-mcp-server"


def test_required_env_vars_contains_token():
    assert "GITHUB_PERSONAL_ACCESS_TOKEN" in REQUIRED_ENV_VARS


def test_optional_env_vars_list():
    assert "GITHUB_TOOLSETS" in OPTIONAL_ENV_VARS
    assert "GITHUB_TOOLS" in OPTIONAL_ENV_VARS
    assert "GITHUB_READ_ONLY" in OPTIONAL_ENV_VARS
    assert "GITHUB_LOCKDOWN_MODE" in OPTIONAL_ENV_VARS
    assert "GITHUB_INSIDERS" in OPTIONAL_ENV_VARS
    assert "GITHUB_HOST" in OPTIONAL_ENV_VARS


def test_get_github_mcp_server_name():
    assert get_github_mcp_server_name() == "github"


def test_create_config_all_optional_vars():
    os.environ["GITHUB_PERSONAL_ACCESS_TOKEN"] = "ghp_test"
    for var in OPTIONAL_ENV_VARS:
        os.environ[var] = f"test_{var}"

    config = create_github_mcp_config()

    for var in OPTIONAL_ENV_VARS:
        assert var in config.env
        assert config.env[var] == f"test_{var}"
