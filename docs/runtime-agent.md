# Agent Runtime

LifeOps Runtime 为每次 Agent 请求生成独立 `run_id`，把运行状态、关键事件、工具策略和失败分类写入本地 SQLite，便于调试、审计和回归测试。

## 核心组件

- `AgentRun`：一次用户请求的生命周期，包含会话、来源、状态、最终输出和错误信息。
- `TraceEvent`：结构化运行事件，按 `run_id + sequence` 递增排序。
- `RuntimeStore`：负责创建 run、更新状态、追加 trace、查询 run/events。
- `TraceRecorder`：Agent、Memory 和 Web 层共享的轻量记录器，trace 写入失败不会中断主流程。
- `ToolPolicyEngine`：工具执行前的策略网关，输出 `allow / ask / deny`。

## Trace 原则

Trace 记录结构化元数据，不写完整大文本。用户输入只记录长度或摘要字段；工具结果记录成功状态、输出长度、错误类型和 metadata；payload 超过 `LIFEOPS_RUNTIME_TRACE_MAX_PAYLOAD_CHARS` 会截断。

首期事件包括：

- `run_started`、`run_completed`、`run_failed`
- `llm_call_started`、`llm_call_finished`、`llm_parse_error`
- `retrieval_route_decided`
- `tool_requested`、`tool_policy_decision`、`tool_result`
- `context_compressed`
- `memory_bootstrap_started`、`memory_bootstrap_finished`、`memory_finalize_*`
- `skill_matched`

## 工具策略

默认 `balanced` 模式：

- 允许只读工具：`builtin.file_read`、`builtin.retrieve_knowledge`、`builtin.web_search`
- `builtin.bash` 只允许安全前缀，拒绝危险命令如 `rm -rf /`、`git reset --hard`
- `builtin.file_edit`、`mcp.*.*` 和未知高风险工具返回 `ask`，首期不会自动执行
- `strict` 模式会拒绝未知工具；`off` 模式允许所有工具

## 查询 API

```http
GET /api/runs/{run_id}
GET /api/conversations/{conversation_id}/runs
GET /api/tools/policy
```

SSE `done` 事件保留 `conversation_id/title`，并追加 `run_id/status`。

## 配置

```bash
LIFEOPS_RUNTIME_ENABLED=true
LIFEOPS_RUNTIME_TRACE_MAX_PAYLOAD_CHARS=12000
LIFEOPS_TOOL_POLICY_MODE=balanced
LIFEOPS_TOOL_POLICY_PATH=.lifeops/tool-policy.json
```

## Eval

```bash
uv run pytest tests/evals -v
uv run pytest tests/evals -m evals -v
```

Eval 不访问真实 LLM、MCP 或网络，后续 runtime、policy、RAG 和 memory 改动都应跑这组回归。
