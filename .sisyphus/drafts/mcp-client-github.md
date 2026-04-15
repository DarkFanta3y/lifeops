# Draft: MCP Client + GitHub MCP Server 接入

## Requirements (confirmed)
- 需要为 lifeops 构建标准 MCP Client（参考官方教程）。
- MCP client 与后续接入的 MCP server 代码放在 `src/lifeops/tools/` 下。
- 首个接入的 MCP server 为 GitHub MCP Server（https://github.com/github/github-mcp-server）。
- 需要完整支持 MCP 能力（tools + resources + prompts）。
- MCP server 配置采用组合方式：CLI 参数 > 环境变量 > 配置文件默认值。
- GitHub 认证信息从环境变量读取。
- 需要多 Server 注册机制（可扩展至其它 MCP 服务）。
- GitHub MCP Server 默认运行方式：本地 Docker（stdio 子进程）。
- 允许 Node 作为子进程（用于 MCP server）。

## Technical Decisions
- 决定：默认使用 stdio（基于 GitHub MCP server）。
- 决定：多 server 注册机制采用“静态 + 动态”组合。
- 决定：配置优先级为 CLI > 环境变量 > 配置文件默认值。
- 决定：支持多 server 注册机制。
- 决定：不新增独立配置文件；优先 CLI + 环境变量，默认值来自 AppConfig。
- 决定：新增 MCP 配置命名约定：环境变量 `LIFEOPS_` 前缀，CLI 参数 `--mcp-*`。
- 决定：采用方案 A（MCP client + 适配层映射到 ToolRegistry）。
- 决定：`LIFEOPS_MCP_SERVERS` 支持 JSON 格式。
- 决定：`--mcp-servers` 使用 JSON 格式。
- 决定：默认不启用自动重连，仅手动触发。
- 决定：动态注册入口采用 Python API（Agent/Manager 层方法）。

## Design Confirmations
- 架构通过：MCP Client Core + MCP Registry Adapter + Server Manager + GitHub MCP Server（Docker stdio）。
- 数据流通过：启动→映射→运行→动态注册。
- 命名策略：`mcp.<server>.<tool>` 前缀。
- 冲突策略：不允许 MCP 工具覆盖本地同名工具。
- 配置策略通过：CLI/ENV + JSON 形式 `LIFEOPS_MCP_SERVERS` 与 `--mcp-servers`。
- 错误处理通过：不抛出未捕获异常，失败返回 ToolResult。
- 重连策略：默认不自动重连。
- 动态注册入口：Python API。
- 测试范围：单元 + 集成。

## Test Strategy Decision
- **Infrastructure exists**: YES（pytest）
- **Automated tests**: YES（实现后补测试）
- **Agent-Executed QA**: ALWAYS
- **Scope**: 单元测试 + 集成测试

## Research Findings
- 现有工具架构：`src/lifeops/tools/base.py` 定义 ToolParams/ToolDefinition/ToolResult/ToolHandler；`src/lifeops/tools/registry.py` 负责注册/执行/生成 OpenAI schema；`src/lifeops/tools/builtin/*` 使用 create_*_tool 工厂注册；`agent.py` 在启动时注册内置工具。
- 扩展点：`Agent.add_tool(definition, handler)` 支持动态注册。
- 约束：ToolParams `extra="forbid"`，参数必须严格匹配；工具名需唯一；handler 必须 async 并返回 ToolResult；registry 捕获异常并返回失败 ToolResult。
- 配置加载：`core/config.py` 环境变量 > .env > 默认值（pydantic-settings）。
- MCP 官方传输：标准支持 stdio 与 Streamable HTTP；官方建议客户端尽可能支持 stdio。来源：https://modelcontextprotocol.io/specification/latest/basic/transports
- MCP 官方客户端职责：连接传输、initialize、list_tools、执行 tool-use 循环、关闭连接。来源：https://modelcontextprotocol.io/docs/develop/build-client
- GitHub MCP Server：远程 URL `https://api.githubcopilot.com/mcp/`；本地可 stdio（Docker/源码 build）。认证环境变量 `GITHUB_PERSONAL_ACCESS_TOKEN`；可选 `GITHUB_TOOLSETS/GITHUB_TOOLS/GITHUB_READ_ONLY/GITHUB_LOCKDOWN_MODE/GITHUB_INSIDERS` 等。来源：https://github.com/github/github-mcp-server 及其 docs。

## Open Questions

- 无（已全部确认）。

## Scope Boundaries
- INCLUDE: MCP client + GitHub MCP Server 接入。
- EXCLUDE: 其它 MCP server（除非明确追加）。
