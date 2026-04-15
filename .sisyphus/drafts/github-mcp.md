# Draft: GitHub MCP 接入 lifeops

## Requirements (confirmed)
- 用户希望接入 GitHub 官方 MCP Server（https://github.com/github/github-mcp-server）
- 代码放置在 `src/lifeops/tools/` 目录
- 接入后需要查看官方提供的工具列表
- 目录结构需遵循主流的 Agent 接入 MCP 格式

## Technical Decisions
- 尚未确认

## Research Findings
- 工具系统核心：`src/lifeops/tools/base.py` + `src/lifeops/tools/registry.py`
- 内置工具注册入口：`src/lifeops/tools/builtin/__init__.py`
- 现有模式：ToolDefinition + ToolParams + handler + registry.register
- 目前未发现 MCP 接入实现（仓库仅内置工具与外部 API 示例）
- 建议新增 `src/lifeops/tools/mcp/` 作为 MCP 接入层
- GitHub MCP 官方：支持远程服务（https://api.githubcopilot.com/mcp/）与本地（Docker/源码 + stdio）
- 工具列表按 toolset 分类，默认含 context/repos/issues/pull_requests/users
- 认证：PAT 或 OAuth（远程）；本地用 `GITHUB_PERSONAL_ACCESS_TOKEN`
- 测试基础设施：pytest（pyproject.toml），示例 `tests/test_agent.py`
- MCP 服务器规范：JSON-RPC 2.0；生命周期 initialize → shutdown
- 标准传输：stdio 或 Streamable HTTP（推荐远程）
- Capabilities：tools/resources/prompts/logging/roots 等
- Tools 注册：schema-first（如 Zod），提供 input/output schema
- 认证：OAuth 2.0 Bearer 或 PAT（视部署方式）
- 参考规范与示例：
  - https://modelcontextprotocol.io/specification
  - https://github.com/modelcontextprotocol/typescript-sdk
  - https://github.com/modelcontextprotocol/servers

## Open Questions
- MCP 认证方式与 token 管理策略
- 期望的接入模式（stdio / HTTP / 其他）
- 是否需要将工具注册到现有 registry
- 是否需要限制 toolset/工具白名单
- 测试策略（TDD/测试后置/不加测试）

## Scope Boundaries
- INCLUDE: GitHub MCP Server 接入与工具可用性检查
- EXCLUDE: 其它第三方 MCP
