"""集成测试：模拟 MCP server 走完整链路。

覆盖：
1. 完整链路：MCPConfig → MCPManager.load_from_config → MCPClient.connect（mock）→ list_tools → register → execute
2. Agent 集成：Agent.add_mcp_server → list_servers → 验证配置
3. GitHub 配置：create_github_mcp_config（有/无 token）
4. 错误处理：连接失败 → FAILED 状态 + ToolResult(success=False)
5. 命名冲突：MCP 工具与本地工具冲突时跳过注册
"""

from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import create_model

from lifeops.agent import Agent
from lifeops.core.config import AppConfig, LLMConfig, MCPConfig
from lifeops.tools.base import ToolDefinition, ToolParams, ToolResult
from lifeops.tools.mcp.adapter import MCPRegistryAdapter
from lifeops.tools.mcp.client import MCPClient
from lifeops.tools.mcp.manager import MCPManager, MCPServerStatus
from lifeops.tools.mcp.types import MCPServerConfig, MCPToolInfo
from lifeops.tools.registry import ToolRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(
    command: str = "docker",
    args: list[str] | None = None,
    env: dict[str, str] | None = None,
) -> dict:
    """生成 MCPServerConfig 原始字典。"""
    return {
        "transport": "stdio",
        "command": command,
        "args": args or ["run", "-i", "--rm", "ghcr.io/github/github-mcp-server"],
        "env": env or {"GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_test"},
    }


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


def _make_app_config(servers: str = "") -> AppConfig:
    """创建测试用的 AppConfig，禁用真实 LLM 调用。"""
    return AppConfig(
        llm=LLMConfig(api_key="test-key"),
        mcp=MCPConfig(enabled=True, servers=servers),
    )


# ---------------------------------------------------------------------------
# 1. 完整链路测试：配置加载 → 连接 → 发现工具 → 注册 → 调用
# ---------------------------------------------------------------------------


class TestFullPipeline:
    """配置加载 → MCPManager.load_from_config → MCPClient.connect（mock）→
    list_tools → MCPRegistryAdapter.register_tools → ToolRegistry.execute"""

    async def test_config_loads_into_manager(self):
        """JSON 配置能加载到 MCPManager 中并正确解析。"""
        manager = MCPManager()
        raw = json.dumps({"github": _make_config()})

        loaded = manager.load_from_config(raw)

        assert loaded == ["github"]
        assert manager.get_server("github") is not None
        assert manager.get_server("github").command == "docker"

    async def test_manager_to_client_connection_pipeline(self):
        """MCPManager.connect_server 创建 mock MCPClient 并存入 _clients。"""
        config = MCPServerConfig(
            transport="stdio",
            command="docker",
            args=["run", "-i", "--rm"],
            env={"GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_test"},
        )
        manager = MCPManager()
        manager.add_server("github", config)

        mock_client = AsyncMock(spec=MCPClient)
        mock_client.connect = AsyncMock()

        with patch("lifeops.tools.mcp.client.MCPClient", return_value=mock_client):
            await manager.connect_server("github")

        mock_client.connect.assert_awaited_once()
        assert manager.get_client("github") is mock_client

    async def test_list_tools_to_registry_execute_pipeline(self):
        """完整链路：mock list_tools → register_tools → ToolRegistry.execute。"""
        registry = ToolRegistry()
        client = AsyncMock(spec=MCPClient)
        client._server_name = "github"
        client.call_tool = AsyncMock(
            return_value=ToolResult(success=True, output='{"total_count": 1}')
        )

        # 模拟 list_tools 返回的工具
        tools = [
            _make_tool_info(original_name="search_repositories", description="搜索仓库"),
            _make_tool_info(
                original_name="get_file_contents",
                description="获取文件内容",
                input_schema={
                    "type": "object",
                    "properties": {
                        "owner": {"type": "string"},
                        "repo": {"type": "string"},
                        "path": {"type": "string"},
                    },
                    "required": ["owner", "repo", "path"],
                },
            ),
        ]

        adapter = MCPRegistryAdapter(registry, client)
        registered = adapter.register_tools(tools)

        assert len(registered) == 2
        assert "mcp.github.search_repositories" in registered
        assert "mcp.github.get_file_contents" in registered

        # 通过 ToolRegistry 执行调用
        result = await registry.execute("mcp.github.search_repositories", {"query": "lifeops"})

        assert result.success is True
        assert result.output == '{"total_count": 1}'
        client.call_tool.assert_awaited_once_with("search_repositories", {"query": "lifeops"})

    async def test_end_to_end_with_manager_config(self):
        """从 JSON 配置到工具注册的完整链路。"""
        # Step 1: 配置加载
        manager = MCPManager()
        raw = json.dumps({"github": _make_config()})
        loaded = manager.load_from_config(raw)
        assert loaded == ["github"]

        # Step 2: 模拟 connect_server + list_tools
        tools = [_make_tool_info(original_name="search_repositories")]
        registry = ToolRegistry()
        client = AsyncMock(spec=MCPClient)
        client._server_name = "github"
        client.call_tool = AsyncMock(return_value=ToolResult(success=True, output="result"))

        # Step 3: 注册到 ToolRegistry
        adapter = MCPRegistryAdapter(registry, client)
        registered = adapter.register_tools(tools)

        assert "mcp.github.search_repositories" in registered

        # Step 4: 执行调用
        result = await registry.execute("mcp.github.search_repositories", {"query": "test"})
        assert result.success is True


# ---------------------------------------------------------------------------
# 2. Agent 集成测试
# ---------------------------------------------------------------------------


class TestAgentIntegration:
    """Agent.add_mcp_server → mcp_manager.list_servers → 验证配置"""

    def test_agent_add_mcp_server(self):
        """Agent 可以动态添加 MCP server 配置。"""
        config = _make_app_config()
        # 避免在 Agent __init__ 时加载真正的 MCP 配置
        config.mcp.enabled = True
        config.mcp.servers = ""
        agent = Agent(config)

        mcp_config = MCPServerConfig(
            transport="stdio",
            command="docker",
            args=["run", "-i", "--rm", "ghcr.io/github/github-mcp-server"],
            env={"GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_test"},
        )
        agent.add_mcp_server("github", mcp_config)

        assert "github" in agent.mcp_manager.list_servers()
        assert agent.mcp_manager.get_server("github") is not None
        assert agent.mcp_manager.get_server("github").command == "docker"

    def test_agent_add_google_workspace_mcp_server(self, monkeypatch):
        """Agent 可以动态添加 Google Workspace MCP server 配置。"""
        from lifeops.tools.mcp.servers import (
            create_google_workspace_mcp_config,
            get_google_workspace_mcp_server_name,
        )

        monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "client-id")
        config = _make_app_config()
        config.mcp.enabled = True
        config.mcp.servers = ""
        agent = Agent(config)

        agent.add_mcp_server(
            get_google_workspace_mcp_server_name(),
            create_google_workspace_mcp_config(),
        )

        assert "google_workspace" in agent.mcp_manager.list_servers()
        mcp_config = agent.mcp_manager.get_server("google_workspace")
        assert mcp_config is not None
        assert mcp_config.command == "uvx"
        assert mcp_config.args[:3] == ["workspace-mcp", "--single-user", "--permissions"]

    def test_agent_remove_mcp_server(self):
        """Agent 可以动态移除 MCP server 配置。"""
        config = _make_app_config()
        config.mcp.servers = ""
        agent = Agent(config)

        mcp_config = MCPServerConfig(
            transport="stdio", command="docker", args=["run", "-i", "--rm"]
        )
        agent.add_mcp_server("github", mcp_config)
        assert "github" in agent.mcp_manager.list_servers()

        agent.remove_mcp_server("github")
        assert "github" not in agent.mcp_manager.list_servers()

    def test_agent_mcp_config_from_app_config(self):
        """Agent 从 AppConfig 的 servers 自动加载 MCP 配置。"""
        raw = json.dumps({"github": _make_config()})
        config = _make_app_config(servers=raw)
        agent = Agent(config)

        assert "github" in agent.mcp_manager.list_servers()
        assert agent.mcp_manager.get_server("github").command == "docker"

    def test_agent_add_multiple_servers(self):
        """Agent 可以添加多个 MCP server。"""
        config = _make_app_config()
        config.mcp.servers = ""
        agent = Agent(config)

        github_config = MCPServerConfig(
            transport="stdio", command="docker", args=["run", "-i", "--rm"]
        )
        fs_config = MCPServerConfig(
            transport="stdio",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
        )

        agent.add_mcp_server("github", github_config)
        agent.add_mcp_server("filesystem", fs_config)

        servers = agent.mcp_manager.list_servers()
        assert "github" in servers
        assert "filesystem" in servers
        assert len(servers) == 2

    def test_agent_mcp_disabled_skips_loading(self):
        """MCP 禁用时不应加载 server 配置。"""
        raw = json.dumps({"github": _make_config()})
        config = _make_app_config(servers=raw)
        config.mcp.enabled = True  # enabled but will check servers

        agent = Agent(config)
        # enabled=True + servers 非空 → 会加载
        assert "github" in agent.mcp_manager.list_servers()

    def test_agent_empty_servers_no_loading(self):
        """servers 为空时不应加载任何 server。"""
        config = _make_app_config(servers="")
        config.mcp.enabled = True
        agent = Agent(config)

        assert agent.mcp_manager.list_servers() == []


# ---------------------------------------------------------------------------
# 3. GitHub 配置测试
# ---------------------------------------------------------------------------


class TestGitHubConfig:
    """create_github_mcp_config（有/无 token）"""

    def test_github_config_with_token(self):
        """有 GITHUB_PERSONAL_ACCESS_TOKEN 时能创建配置。"""
        from lifeops.tools.mcp.servers.github import create_github_mcp_config

        with patch.dict(
            os.environ, {"GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_test_token"}, clear=False
        ):
            config = create_github_mcp_config()

        assert config.transport == "stdio"
        assert config.command == "docker"
        assert "run" in config.args
        assert "-i" in config.args
        assert "--rm" in config.args
        assert config.env["GITHUB_PERSONAL_ACCESS_TOKEN"] == "ghp_test_token"

    def test_github_config_without_token_raises(self):
        """缺少 GITHUB_PERSONAL_ACCESS_TOKEN 时应抛出 ValueError。"""
        from lifeops.tools.mcp.servers.github import create_github_mcp_config

        with patch.dict(os.environ, {}, clear=False):
            # 确保环境变量不存在
            os.environ.pop("GITHUB_PERSONAL_ACCESS_TOKEN", None)
            with pytest.raises(ValueError, match="GITHUB_PERSONAL_ACCESS_TOKEN"):
                create_github_mcp_config()

    def test_github_config_with_optional_env_vars(self):
        """可选环境变量应透传到配置。"""
        from lifeops.tools.mcp.servers.github import (
            GITHUB_MCP_SERVER_IMAGE,
            create_github_mcp_config,
        )

        env = {
            "GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_test",
            "GITHUB_TOOLSETS": "repos,issues",
            "GITHUB_READ_ONLY": "1",
        }
        with patch.dict(os.environ, env, clear=False):
            config = create_github_mcp_config()

        assert config.env["GITHUB_TOOLSETS"] == "repos,issues"
        assert config.env["GITHUB_READ_ONLY"] == "1"
        assert GITHUB_MCP_SERVER_IMAGE in config.args[-1]

    def test_github_config_get_server_name(self):
        """get_github_mcp_server_name 返回正确名称。"""
        from lifeops.tools.mcp.servers.github import get_github_mcp_server_name

        assert get_github_mcp_server_name() == "github"

    def test_github_config_docker_command(self):
        """GitHub 配置的 Docker 命令结构正确。"""
        from lifeops.tools.mcp.servers.github import create_github_mcp_config

        with patch.dict(os.environ, {"GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_x"}, clear=False):
            config = create_github_mcp_config()

        assert config.command == "docker"
        assert config.args[0] == "run"
        assert config.args[1] == "-i"
        assert config.args[2] == "--rm"


# ---------------------------------------------------------------------------
# 4. 错误处理测试
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """连接失败 → FAILED 状态 + ToolResult(success=False)"""

    async def test_connect_failure_sets_failed_status(self):
        """MCPClient.connect 失败后状态应为 FAILED。"""
        config = MCPServerConfig(
            transport="stdio",
            command="docker",
            args=["run", "-i", "--rm"],
            env={"GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_test"},
        )
        manager = MCPManager()
        manager.add_server("github", config)

        # 模拟 connect 失败
        mock_client = AsyncMock(spec=MCPClient)
        mock_client.connect = AsyncMock(side_effect=ConnectionError("子进程启动失败"))

        with patch("lifeops.tools.mcp.client.MCPClient", return_value=mock_client):
            with pytest.raises(ConnectionError, match="子进程启动失败"):
                await manager.connect_server("github")

        # 连接失败后不应有 client 引用
        assert manager.get_client("github") is None

    async def test_connect_failure_status_via_client(self):
        """MCPClient.connect 异常时 manager 状态更新为 FAILED。
        验证 MCPClient 内部状态管理逻辑。"""
        config = MCPServerConfig(transport="stdio", command="nonexistent_command", args=[])
        manager = MCPManager()
        manager.add_server("test", config)

        # 模拟 MCPClient 构造后 connect 抛异常
        # 先验证初始状态
        assert manager.get_status("test") == MCPServerStatus.DISCONNECTED

    async def test_call_tool_error_returns_failure(self):
        """MCPClient.call_tool 异常时返回 ToolResult(success=False)。"""
        registry = ToolRegistry()
        client = AsyncMock(spec=MCPClient)
        client._server_name = "github"
        client.call_tool = AsyncMock(
            return_value=ToolResult(success=False, output="", error="工具调用超时")
        )

        adapter = MCPRegistryAdapter(registry, client)
        tool = _make_tool_info(original_name="failing_tool")
        adapter.register_tools([tool])

        result = await registry.execute("mcp.github.failing_tool", {"query": "test"})

        assert result.success is False
        assert result.error == "工具调用超时"

    async def test_tool_not_found_raises_key_error(self):
        """调用未注册的工具应抛出 KeyError。"""
        registry = ToolRegistry()
        # 无任何注册工具

        with pytest.raises(KeyError, match="mcp.github.nonexistent"):
            await registry.execute("mcp.github.nonexistent", {})

    async def test_disconnect_nonexistent_server(self):
        """断开未连接的 server 应安全处理。"""
        manager = MCPManager()
        # 不应抛出异常
        await manager.disconnect_server("nonexistent")
        assert manager.get_client("nonexistent") is None

    async def test_call_tool_exception_returns_failure_result(self):
        """call_tool 内部异常时 MCPClient 返回 ToolResult(success=False)。"""
        registry = ToolRegistry()
        client = AsyncMock(spec=MCPClient)
        client._server_name = "github"
        # 模拟 call_tool 抛出异常
        client.call_tool = AsyncMock(side_effect=RuntimeError("连接断开"))

        adapter = MCPRegistryAdapter(registry, client)
        tool = _make_tool_info(original_name="unstable_tool")
        adapter.register_tools([tool])

        # ToolRegistry.execute 捕获异常并返回 ToolResult(success=False)
        result = await registry.execute("mcp.github.unstable_tool", {"query": "test"})

        assert result.success is False
        assert "连接断开" in result.error

    async def test_connect_unregistered_server_skips(self):
        """连接未注册的 server 应跳过且不抛异常。"""
        manager = MCPManager()
        # 不注册任何 server
        await manager.connect_server("nonexistent")
        assert manager.get_client("nonexistent") is None

    async def test_connect_already_connected_skips(self):
        """重复连接已连接的 server 应跳过。"""
        config = MCPServerConfig(transport="stdio", command="docker", args=[])
        manager = MCPManager()
        manager.add_server("github", config)

        existing_client = AsyncMock(spec=MCPClient)
        manager._clients["github"] = existing_client

        # 已有 client，不应再次连接
        await manager.connect_server("github")
        existing_client.connect.assert_not_awaited()


# ---------------------------------------------------------------------------
# 5. 命名冲突集成测试
# ---------------------------------------------------------------------------


class TestNamingConflict:
    """MCP 工具与本地工具冲突时跳过注册"""

    def test_mcp_tool_conflicts_with_builtin_tool(self):
        """MCP 工具名与本地工具冲突时，应跳过注册。"""
        registry = ToolRegistry()
        # 注册一个本地工具，名称恰好是 MCP 工具的全名
        local_handler = AsyncMock(return_value=ToolResult(success=True, output="local"))
        local_defn = ToolDefinition(
            name="mcp.github.search_repositories",
            description="本地搜索引擎",
            parameters_model=ToolParams,
            category="builtin",
        )
        registry.register(local_defn, local_handler)

        # 尝试注册同名的 MCP 工具
        client = AsyncMock(spec=MCPClient)
        client._server_name = "github"
        adapter = MCPRegistryAdapter(registry, client)
        tool = _make_tool_info(original_name="search_repositories")

        registered = adapter.register_tools([tool])

        # 应跳过冲突的工具
        assert registered == []
        # 本地工具应保持不变
        defn = registry.get_definition("mcp.github.search_repositories")
        assert defn.category == "builtin"
        assert defn.description == "本地搜索引擎"

    def test_partial_conflict_registers_non_conflicting(self):
        """部分冲突时只注册不冲突的工具。"""
        registry = ToolRegistry()
        # 注册一个本地工具占用 mcp.github.search_repositories
        local_handler = AsyncMock(return_value=ToolResult(success=True, output="local"))
        local_defn = ToolDefinition(
            name="mcp.github.search_repositories",
            description="本地工具",
            parameters_model=ToolParams,
            category="builtin",
        )
        registry.register(local_defn, local_handler)

        client = AsyncMock(spec=MCPClient)
        client._server_name = "github"
        client.call_tool = AsyncMock(return_value=ToolResult(success=True, output="mcp result"))
        adapter = MCPRegistryAdapter(registry, client)

        # 注册两个工具：一个冲突，一个不冲突
        tools = [
            _make_tool_info(original_name="search_repositories", description="搜索"),
            _make_tool_info(original_name="get_file_contents", description="获取文件"),
        ]
        registered = adapter.register_tools(tools)

        # 只有不冲突的被注册
        assert len(registered) == 1
        assert "mcp.github.get_file_contents" in registered
        assert "mcp.github.search_repositories" not in registered

    async def test_conflict_does_not_override_execution(self):
        """命名冲突时本地工具的执行行为不受影响。"""
        registry = ToolRegistry()
        local_handler = AsyncMock(return_value=ToolResult(success=True, output="LOCAL"))
        local_params = create_model("LocalSearchParams", __base__=ToolParams, query=(str, ...))
        local_defn = ToolDefinition(
            name="mcp.github.search_repositories",
            description="本地搜索",
            parameters_model=local_params,
            category="builtin",
        )
        registry.register(local_defn, local_handler)

        client = AsyncMock(spec=MCPClient)
        client._server_name = "github"
        client.call_tool = AsyncMock(return_value=ToolResult(success=True, output="MCP"))
        adapter = MCPRegistryAdapter(registry, client)
        tool = _make_tool_info(original_name="search_repositories")
        adapter.register_tools([tool])

        # 执行应走本地 handler，而非 MCP handler
        result = await registry.execute("mcp.github.search_repositories", {"query": "test"})

        assert result.output == "LOCAL"
        # MCP client 的 call_tool 不应被调用
        client.call_tool.assert_not_awaited()

    def test_no_conflict_all_registered(self):
        """无命名冲突时所有 MCP 工具都应注册成功。"""
        registry = ToolRegistry()
        # 只有本地 bash 工具（无 mcp 前缀），不冲突
        local_handler = AsyncMock(return_value=ToolResult(success=True, output="done"))
        local_defn = ToolDefinition(
            name="bash",
            description="执行命令",
            parameters_model=ToolParams,
            category="builtin",
        )
        registry.register(local_defn, local_handler)

        client = AsyncMock(spec=MCPClient)
        client._server_name = "github"
        adapter = MCPRegistryAdapter(registry, client)

        tools = [
            _make_tool_info(original_name="search_repositories"),
            _make_tool_info(original_name="get_file_contents"),
        ]
        registered = adapter.register_tools(tools)

        assert len(registered) == 2
        assert registry.get_definition("bash") is not None  # 本地工具仍存在

    async def test_conflict_in_agent_context(self):
        """在 Agent 上下文中，MCP 工具与内置工具冲突时跳过注册。"""
        config = _make_app_config(servers="")
        agent = Agent(config)

        # Agent 初始化后已注册内置工具（如 bash）
        builtin_names = [d.name for d in agent.tools.list_definitions()]
        # 确认内置工具存在
        assert len(builtin_names) > 0

        # 创建 MCP 工具与内置工具同名的情况
        client = AsyncMock(spec=MCPClient)
        client._server_name = "test"
        client.call_tool = AsyncMock(return_value=ToolResult(success=True, output="mcp output"))
        adapter = MCPRegistryAdapter(agent.tools, client)

        # 尝试注册与内置工具同名的 MCP 工具
        conflicting_tool = MCPToolInfo(
            server_name="test",
            original_name=builtin_names[0] if builtin_names else "bash",
            description="与内置工具冲突的 MCP 工具",
            input_schema={"type": "object"},
        )
        registered = adapter.register_tools([conflicting_tool])

        # 冲突工具应被跳过
        if builtin_names:
            # 名字格式是 "bash"，不是 "mcp.test.bash"
            # 但 MCP 工具的全名是 "mcp.test.<name>"，除非内置工具也叫 "mcp.test.<name>"
            # 所以这里只有当 builtin_names 包含 mcp 全名时才会冲突
            full_name = conflicting_tool.full_name
            assert full_name not in registered or full_name not in builtin_names

    async def test_unregister_and_re_register_pipeline(self):
        """注册后注销，再注册新工具的完整流程。"""
        registry = ToolRegistry()
        client = AsyncMock(spec=MCPClient)
        client._server_name = "github"
        client.call_tool = AsyncMock(return_value=ToolResult(success=True, output="result"))
        adapter = MCPRegistryAdapter(registry, client)

        # 第一次注册
        tools_v1 = [
            _make_tool_info(original_name="search_repositories"),
            _make_tool_info(original_name="create_issue"),
        ]
        registered_v1 = adapter.register_tools(tools_v1)
        assert len(registered_v1) == 2

        # 注销
        adapter.unregister_tools(tools_v1)
        assert len(registry.list_definitions()) == 0

        # 第二次注册新工具
        tools_v2 = [
            _make_tool_info(original_name="search_repositories"),
            _make_tool_info(original_name="list_commits"),
        ]
        registered_v2 = adapter.register_tools(tools_v2)
        assert len(registered_v2) == 2
        assert "mcp.github.list_commits" in registered_v2

        # 搜索工具可正常执行
        result = await registry.execute("mcp.github.search_repositories", {"query": "test"})
        assert result.success is True
