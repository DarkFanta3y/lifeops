# Learnings — MCP Client + GitHub MCP Server

## 2026-04-15: Project Architecture
- Tool system: `src/lifeops/tools/base.py` defines ToolParams/ToolDefinition/ToolResult/ToolHandler
- ToolParams uses `extra="forbid"` — strict validation, no extra fields
- ToolRegistry in `src/lifeops/tools/registry.py` — register/execute/get_openai_tool_schemas
- Agent in `src/lifeops/agent.py` — creates ToolRegistry, calls register_all_builtin_tools, has add_tool()
- Config in `src/lifeops/core/config.py` — pydantic-settings with env_prefix pattern (LLM_, LIFEOPS_, LIFEOPS_CONTEXT_)
- Built-in tools use factory pattern: `create_*_tool(registry)` in `src/lifeops/tools/builtin/`
- Tests use pytest-asyncio with `asyncio_mode = "auto"`
- Ruff: line-length 100, target Python 3.13

## 2026-04-15: MCP Protocol
- MCP supports stdio and Streamable HTTP transports
- stdio: client starts subprocess, communicates via stdin/stdout JSON-RPC
- Client lifecycle: connect → initialize → list_tools/resources/prompts → call_tool → close
- GitHub MCP Server: Docker stdio, requires GITHUB_PERSONAL_ACCESS_TOKEN
- Optional env vars: GITHUB_TOOLSETS, GITHUB_TOOLS, GITHUB_READ_ONLY, GITHUB_LOCKDOWN_MODE, GITHUB_INSIDERS

## 2026-04-15: Design Decisions
- MCP tools use `mcp.<server>.<tool>` prefix — no override of local tools
- Resources/prompts exposed via MCP Manager API, not as ToolRegistry tools
- No auto-reconnect by default
- Dynamic registration via Python API only (no CLI commands)
- Config: CLI > ENV > defaults, no separate config file
## 2026-04-15: MCPManager Implementation
- MCPManager 在 `src/lifeops/tools/mcp/manager.py`，管理 MCPServerConfig 的注册和状态
- 静态注册：`load_from_config(servers_raw: str)` 解析 JSON 字符串，为每个条目创建 MCPServerConfig
- 动态注册：`add_server(name, config)` / `remove_server(name)`
- MCPServerStatus 枚举：DISCONNECTED / CONNECTING / CONNECTED / READY / FAILED
- 状态存储在 `_status` dict 中，新注册默认为 DISCONNECTED
- add_server 名称冲突时覆盖并打印 warning；remove_server 名称不存在时打印 warning
- load_from_config 对无效 JSON、非 dict 顶层、非 dict 值、MCPServerConfig 验证失败都有容错处理
- MCPServerConfig 使用 Pydantic BaseModel，字段有默认值（transport="stdio", args=[], env={}）
- `__init__.py` 已更新，导出 MCPManager 和 MCPServerStatus

## 2026-04-15: MCPClient Implementation
- `src/lifeops/tools/mcp/client.py` — MCPClient 类，stdio 传输 + AsyncExitStack 生命周期管理
- 使用 `mcp` SDK v1.27.0：`StdioServerParameters`, `stdio_client`, `ClientSession`
- `stdio_client(params)` 是 async context manager，返回 (read_stream, write_stream)
- `ClientSession` 也是 async context manager，必须先调用 `initialize()` 才能进行其他操作
- 用 `AsyncExitStack` 管理两个嵌套的 async context manager（stdio_client + ClientSession）
- `_cleanup()` 安全关闭所有资源：清空缓存 → aclose exit_stack → 设置 DISCONNECTED
- `connect()` 失败时：状态设为 FAILED → 日志异常 → 调用 _cleanup() → re-raise
- `call_tool()` 将 MCP `CallToolResult` 转换为 lifeops `ToolResult`：
  - isError=True → ToolResult(success=False, ...)
  - TextContent → 提取 .text 作为 output
  - 其他 ContentBlock → model_dump_json 序列化
  - 调用异常 → ToolResult(success=False, error=str(exc))
- MCP SDK 类型：ListToolsResult.tools, ListResourcesResult.resources, ListPromptsResult.prompts
- Tool: name, description, inputSchema; Resource: uri, name, description, mimeType; Prompt: name, description, arguments
- PromptArgument: name (required), description (optional), required (optional bool)
- `mcp` SDK 依赖添加：`uv add "mcp[cli]"` → v1.27.0
- `_extract_text_from_content` 是模块级函数（非方法），便于测试
- `MCPServerConfig.env` 默认是 `{}`（空 dict），但 `StdioServerParameters.env` 需要 `None` 或 dict → 用 `self._config.env or None` 转换

## 2026-04-15: MCPRegistryAdapter Implementation
- `src/lifeops/tools/mcp/adapter.py` — MCPRegistryAdapter 类，桥接 MCP 工具到 ToolRegistry
- `register_tools(tools: list[MCPToolInfo]) -> list[str]`：遍历工具列表，检查冲突后注册，返回成功注册的全名列表
- `unregister_tools(tools: list[MCPToolInfo])`：从 ToolRegistry 内部 dict 中删除定义和 handler
- 动态 ToolParams 子类使用 `pydantic.create_model(__base__=ToolParams, **field_definitions)` 生成
- 字段映射：JSON Schema required → pydantic 必填字段；非 required → `(type | None, None)`
- `_json_schema_type_to_python` 映射：string→str, integer→int, number→float, boolean→bool, array→list, object→dict
- 无 properties 的工具（input_schema 只有 type: object）返回空的 ToolParams 子类
- Handler 是闭包：`async def handler(params) -> ToolResult: return await client.call_tool(original_name, params)`
- 命名冲突用 `is_conflicting_name(full_name, registry)` 检测，冲突时跳过并 warning
- ToolDefinition.category 设为 "mcp" 区分本地工具
- `__init__.py` 已更新导出 MCPRegistryAdapter
- 测试 14 个用例覆盖：单/多注册、handler 调用、错误传播、冲突跳过、空列表、参数校验、类型映射、注销、端到端流程

## 2026-04-16: MCPManager Resources/Prompts Access + Client Lifecycle

### MCPManager 新增方法
- `_clients: dict[str, Any]` — 管理 MCPClient 实例引用（key=server_name）
- `connect_server(name)` — 创建 MCPClient 实例并连接，已连接/未注册时跳过
- `disconnect_server(name)` — 关闭连接并移除引用
- `get_client(name)` — 获取 MCPClient 实例，未连接返回 None
- `list_mcp_resources(server_name)` — 列出资源，未连接返回空列表
- `list_mcp_prompts(server_name)` — 列出提示词，未连接返回空列表
- `read_resource(server_name, uri)` — 读取资源内容，未连接抛 RuntimeError
- `get_prompt(server_name, prompt_name, arguments)` — 获取提示词，未连接抛 RuntimeError

### MCPClient 新增方法
- `read_resource(uri: str) -> str` — 读取资源内容，TextResourceContents→text, BlobResourceContents→blob, 其他→JSON
- `get_prompt(name: str, arguments: dict[str, str] | None) -> str` — 获取提示词，格式化为 `[role]: text`

### 命名策略（types.py 新增函数）
- `make_mcp_resource_uri(server, path)` → `mcp://<server>/<path>` 格式
- `make_mcp_prompt_name(server, prompt)` → `mcp.<server>.<prompt>` 格式
- 资源和提示词仅通过 Manager API 暴露，不注册到 ToolRegistry

### 关键设计决策
- connect_server 内部使用 lazy import (`from lifeops.tools.mcp.client import MCPClient`) 避免循环导入
- remove_server 不自动断开客户端（需先 disconnect_server），因为 close() 是异步方法
- list_mcp_resources/list_mcp_prompts 未连接时返回空列表（非异常）
- read_resource/get_prompt 未连接时抛 RuntimeError（与 MCPClient._ensure_connected 一致）

### 测试
- tests/test_mcp_manager_client.py — 16 个用例覆盖连接生命周期、资源/提示词访问、未连接处理
- 使用 unittest.mock.AsyncMock 和 patch 模拟 MCPClient
- patch 路径为 `lifeops.tools.mcp.client.MCPClient`（因为 connect_server 使用 lazy import）

## 2026-04-16: 集成测试编写

### 测试文件：tests/test_mcp_integration.py（29 个用例）

- **关键发现**：mock MCPClient 时不能直接验证内部状态变更（如 MCPServerStatus.READY），因为 mock 不会执行真实 connect() 中的状态管理逻辑。应改为验证 mock 方法被调用和 _clients dict 中存储了引用。
- **ToolParams 验证**：本地 mock 工具的 parameters_model 不能用裸 `ToolParams`（extra="forbid"），需要用 `create_model("Name", __base__=ToolParams, field=(type, ...))` 创建带字段的子类，否则 `_validate_params` 会拒绝有额外字段的参数。
- **测试风格**：使用 `unittest.mock.AsyncMock` + `patch` 模拟 MCP SDK，不依赖真实 Docker 或 GitHub 账号。
- **MCPServerConfig import**：在文件顶部集中 import，避免方法体内重复 import。

### 测试覆盖场景
1. 完整链路：MCPConfig → MCPManager.load_from_config → MCPClient.connect（mock）→ list_tools → register → execute（4 个用例）
2. Agent 集成：add_mcp_server / remove_mcp_server / config auto-loading / multiple servers / disabled / empty（6 个用例）
3. GitHub 配置：有 token / 无 token / 可选 env / server name / docker command（5 个用例）
4. 错误处理：connect failure / status tracking / call_tool error / tool not found / disconnect nonexistent / call_tool exception / connect unregistered / connect already connected（8 个用例）
5. 命名冲突：conflict with builtin / partial conflict / execution doesn't override / no conflict / agent context conflict / unregister re-register（6 个用例）

### 总测试数：202 全部通过（原 112 + 新增 29 + 原有补充 ≈ 202）
