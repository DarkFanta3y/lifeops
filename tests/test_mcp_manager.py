from __future__ import annotations

import json

from lifeops.tools.mcp.manager import MCPManager, MCPServerStatus
from lifeops.tools.mcp.types import MCPServerConfig


def test_add_server_basic():
    manager = MCPManager()
    config = MCPServerConfig(transport="stdio", command="docker", args=["run", "-i", "--rm"])
    manager.add_server("github", config)

    assert "github" in manager.list_servers()
    assert manager.get_server("github") is not None
    assert manager.get_server("github").command == "docker"
    assert manager.get_status("github") == MCPServerStatus.DISCONNECTED


def test_add_server_overwrites_existing():
    manager = MCPManager()
    config_v1 = MCPServerConfig(transport="stdio", command="docker", args=["v1"])
    config_v2 = MCPServerConfig(transport="stdio", command="npx", args=["v2"])

    manager.add_server("github", config_v1)
    manager.add_server("github", config_v2)

    assert manager.get_server("github").command == "npx"
    assert len(manager.list_servers()) == 1


def test_remove_server():
    manager = MCPManager()
    config = MCPServerConfig(transport="stdio", command="docker")
    manager.add_server("github", config)

    manager.remove_server("github")
    assert "github" not in manager.list_servers()
    assert manager.get_server("github") is None


def test_remove_nonexistent_server():
    manager = MCPManager()
    manager.remove_server("nonexistent")
    assert len(manager.list_servers()) == 0


def test_remove_server_clears_status():
    manager = MCPManager()
    config = MCPServerConfig(transport="stdio", command="docker")
    manager.add_server("test-server", config)
    assert manager.get_status("test-server") == MCPServerStatus.DISCONNECTED

    manager.remove_server("test-server")
    assert manager.get_status("test-server") == MCPServerStatus.DISCONNECTED


def test_load_from_config_single_server():
    manager = MCPManager()
    raw = json.dumps(
        {
            "github": {
                "transport": "stdio",
                "command": "docker",
                "args": ["run", "-i", "--rm", "ghcr.io/github/github-mcp-server"],
                "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_xxx"},
            }
        }
    )

    loaded = manager.load_from_config(raw)
    assert loaded == ["github"]
    assert manager.get_server("github").command == "docker"
    assert manager.get_server("github").env == {"GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_xxx"}


def test_load_from_config_multiple_servers():
    manager = MCPManager()
    raw = json.dumps(
        {
            "github": {
                "transport": "stdio",
                "command": "docker",
                "args": ["run", "-i", "--rm", "ghcr.io/github/github-mcp-server"],
            },
            "filesystem": {
                "transport": "stdio",
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
            },
        }
    )

    loaded = manager.load_from_config(raw)
    assert set(loaded) == {"github", "filesystem"}
    assert len(manager.list_servers()) == 2


def test_load_from_config_invalid_json():
    manager = MCPManager()
    loaded = manager.load_from_config("not valid json {{{")
    assert loaded == []
    assert len(manager.list_servers()) == 0


def test_load_from_config_empty_string():
    manager = MCPManager()
    loaded = manager.load_from_config("")
    assert loaded == []
    assert len(manager.list_servers()) == 0


def test_load_from_config_whitespace_only():
    manager = MCPManager()
    loaded = manager.load_from_config("   \n\t  ")
    assert loaded == []


def test_load_from_config_non_dict_top_level():
    manager = MCPManager()
    raw = json.dumps(["not", "a", "dict"])
    loaded = manager.load_from_config(raw)
    assert loaded == []


def test_load_from_config_invalid_server_entry():
    manager = MCPManager()
    raw = json.dumps(
        {
            "valid": {"transport": "stdio", "command": "docker"},
            "invalid": "not_a_dict",
        }
    )

    loaded = manager.load_from_config(raw)
    assert loaded == ["valid"]
    assert manager.get_server("valid") is not None
    assert manager.get_server("invalid") is None


def test_load_from_config_missing_optional_fields():
    manager = MCPManager()
    raw = json.dumps(
        {
            "minimal": {"transport": "stdio", "command": "npx"},
        }
    )

    loaded = manager.load_from_config(raw)
    assert loaded == ["minimal"]
    server = manager.get_server("minimal")
    assert server.args == []
    assert server.env == {}


def test_get_server_nonexistent():
    manager = MCPManager()
    assert manager.get_server("nonexistent") is None


def test_get_status_nonexistent():
    manager = MCPManager()
    assert manager.get_status("nonexistent") == MCPServerStatus.DISCONNECTED


def test_list_servers_empty():
    manager = MCPManager()
    assert manager.list_servers() == []


def test_list_servers_after_operations():
    manager = MCPManager()
    config = MCPServerConfig(transport="stdio", command="docker")

    manager.add_server("a", config)
    manager.add_server("b", config)
    manager.remove_server("a")

    servers = manager.list_servers()
    assert servers == ["b"]


def test_server_status_initial_state():
    manager = MCPManager()
    config = MCPServerConfig(transport="stdio", command="docker")
    manager.add_server("test", config)

    assert manager.get_status("test") == MCPServerStatus.DISCONNECTED


def test_server_status_enum_values():
    assert MCPServerStatus.DISCONNECTED == "disconnected"
    assert MCPServerStatus.CONNECTING == "connecting"
    assert MCPServerStatus.CONNECTED == "connected"
    assert MCPServerStatus.READY == "ready"
    assert MCPServerStatus.FAILED == "failed"


def test_load_from_config_defaults_to_stdio():
    manager = MCPManager()
    raw = json.dumps(
        {
            "server": {"command": "npx"},
        }
    )

    loaded = manager.load_from_config(raw)
    assert loaded == ["server"]
    assert manager.get_server("server").transport == "stdio"


def test_add_and_load_combined():
    manager = MCPManager()
    dynamic_config = MCPServerConfig(transport="stdio", command="docker")
    manager.add_server("dynamic", dynamic_config)

    raw = json.dumps(
        {
            "static": {"transport": "stdio", "command": "npx"},
        }
    )
    manager.load_from_config(raw)

    assert set(manager.list_servers()) == {"dynamic", "static"}
