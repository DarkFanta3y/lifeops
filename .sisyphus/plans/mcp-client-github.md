# MCP Client + GitHub MCP Server 接入计划

## TL;DR

> **Quick Summary**: 在 lifeops 现有 ToolRegistry 体系内引入标准 MCP Client（stdio），接入 GitHub MCP Server（Docker 子进程），支持 tools/resources/prompts，多 server 静态+动态注册，配置仅用 CLI/ENV。
>
> **Deliverables**:
> - MCP Client Core + Registry Adapter + Server Manager（放在 `src/lifeops/tools/`）
> - GitHub MCP Server（Docker stdio）默认接入
> - 多 server 静态注册 JSON 配置 + 动态注册 Python API
> - 单元 + 集成测试（实现后补测试）
>
> **Estimated Effort**: Medium
> **Parallel Execution**: YES — 3 waves
> **Critical Path**: 配置模型 → MCP Client Core → Adapter 注册 → GitHub 接入 → 集成测试

---

## Context

### Original Request
为 lifeops 构建标准 MCP client（参考官方教程），接入 GitHub MCP Server，代码放在 `src/lifeops/tools/`，支持 tools/resources/prompts，多 server（静态+动态），配置 CLI/ENV 优先级并使用 JSON。

### Interview Summary
**Key Discussions**:
- 传输：默认 stdio（基于 GitHub MCP server）
- GitHub MCP Server：本地 Docker stdio 子进程
- 多 server：静态 + 动态（动态入口为 Python API）
- 配置：CLI > ENV > 默认值，无独立配置文件
- 命名：`mcp.<server>.<tool>` 前缀，不覆盖本地工具
- 自动重连：默认关闭
- 测试：pytest，**实现后补测试**，单元 + 集成

**Research Findings**:
- MCP 官方客户端教程与传输规范（stdio/Streamable HTTP）
- GitHub MCP Server 官方运行方式与环境变量
- lifeops 工具系统结构（ToolRegistry/ToolDefinition/ToolParams/ToolResult）

### Metis Review
**Identified Gaps** (addressed):
- 无新增关键缺口（已明确命名/冲突策略/动态入口/测试范围）

---

## Work Objectives

### Core Objective
在不增加项目目录复杂度的前提下，将 MCP Client 集成进现有 ToolRegistry，标准化接入 GitHub MCP Server 并建立可扩展的多 server 注册机制。

### Concrete Deliverables
- MCP Client Core（stdio 连接、initialize/list/call/close）
- MCP Registry Adapter（MCP → ToolRegistry 映射）
- Server Manager（静态 JSON + 动态 API）
- GitHub MCP Server 默认配置与启动命令模板
- 单元 + 集成测试

### Definition of Done
- [ ] 启动 lifeops 后可列出 `mcp.github.*` 工具
- [ ] 可通过 ToolRegistry 调用 GitHub MCP 工具并返回 ToolResult
- [ ] 单元测试 + 集成测试通过（pytest）

### Must Have
- 完整支持 MCP 的 tools/resources/prompts
- 多 server 静态注册（JSON）+ 动态注册 API
- CLI/ENV 优先级：CLI > ENV > 默认值

### Must NOT Have (Guardrails)
- 不新增独立配置文件/目录
- MCP 工具不得覆盖本地同名工具
- 不默认启用自动重连

---

## Verification Strategy (MANDATORY)

> **ZERO HUMAN INTERVENTION** — 全部由 agent 执行验证。

### Test Decision
- **Infrastructure exists**: YES（pytest）
- **Automated tests**: YES（实现后补测试）
- **Framework**: pytest

### QA Policy
每个任务必须包含 **Agent-Executed QA Scenarios**，证据保存到 `.sisyphus/evidence/task-{N}-{scenario-slug}.{ext}`。

---

## Execution Strategy

### Parallel Execution Waves

Wave 1（基础与配置）
├── Task 1: AppConfig/CLI 配置扩展（JSON + 前缀）
├── Task 2: MCP 接口与类型定义（ToolParams/ToolResult 适配）
├── Task 3: Server Manager 结构设计（静态/动态注册 API）
├── Task 4: GitHub MCP Server 运行模板与 env 映射
└── Task 5: 项目文档更新（PROJECT.md）

Wave 2（核心实现）
├── Task 6: MCP Client Core（stdio 子进程 + initialize/list/call）
├── Task 7: MCP Registry Adapter（映射到 ToolRegistry）
├── Task 8: 动态注册 API 接口（Agent/Manager 层）
└── Task 9: resources/prompts 支持与命名冲突策略

Wave 3（测试与集成）
├── Task 10: 单元测试（adapter/manager/client）
└── Task 11: 集成测试（模拟 MCP server / GitHub 接入）

### Dependency Matrix (full)
- **1**: — → 6,7,8,9,10,11
- **2**: — → 7,10
- **3**: — → 8,10,11
- **4**: — → 11
- **5**: —
- **6**: 1 → 7,9,10,11
- **7**: 1,2,6 → 9,10,11
- **8**: 1,3 → 11
- **9**: 6,7 → 10,11
- **10**: 1,2,6,7,9 → 11
- **11**: 1,3,4,6,7,8,9,10 → Final Verification

### Agent Dispatch Summary
- Wave 1: Tasks 1-5 → `quick` / `unspecified-low`
- Wave 2: Tasks 6-9 → `unspecified-high`
- Wave 3: Tasks 10-11 → `unspecified-high`

---

## TODOs

- [x] 1. 扩展 AppConfig/CLI：MCP 全局配置（JSON + 优先级）

  **What to do**:
  - 在 `core/config.py` 中新增 MCP 配置字段（启用开关、默认传输、servers JSON 字符串）
  - 在 CLI 入口（`agent.py:main`）解析 `--mcp-*` 参数并覆盖 AppConfig（优先级最高）
  - 明确 JSON 结构约束与校验错误信息（无独立配置文件）

  **Must NOT do**:
  - 不新增独立配置文件或目录

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 小范围配置与 CLI 参数扩展
  - **Skills**: [`coding-standards`]
    - `coding-standards`: 保障配置与 CLI 解析保持一致性
  - **Skills Evaluated but Omitted**:
    - `api-design`: 非 API 设计任务

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 2-5)
  - **Blocks**: 6,7,8,9,10,11
  - **Blocked By**: None

  **References**:
  - `src/lifeops/core/config.py` — AppConfig 模式与 env_prefix 约定
  - `src/lifeops/agent.py:main()` — CLI 入口位置
  - `README.md:配置章节` — 配置优先级与命名约定
  - 官方 MCP 传输规范 — https://modelcontextprotocol.io/specification/latest/basic/transports

  **Acceptance Criteria**:
  - [ ] `LIFEOPS_MCP_*` 环境变量可被 AppConfig 读取
  - [ ] `--mcp-*` 参数覆盖 env 值（CLI > ENV）
  - [ ] JSON 解析失败时返回清晰错误信息

  **QA Scenarios**:
  
  Scenario: 使用 ENV 加载 JSON 配置
    Tool: Bash
    Preconditions: 设置 `LIFEOPS_MCP_SERVERS` 为有效 JSON
    Steps:
      1. 运行 `LIFEOPS_MCP_SERVERS='{"github": {"transport": "stdio"}}' uv run python - <<'PY'
import os
from lifeops.core.config import AppConfig
cfg = AppConfig()
print(cfg.mcp.servers_raw)
PY`
    Expected Result: 输出包含 `github` 且无异常
    Evidence: .sisyphus/evidence/task-1-env-json.txt

  Scenario: CLI 覆盖 ENV
    Tool: Bash
    Preconditions: ENV 设置为 A，CLI 设置为 B
    Steps:
      1. 运行 `LIFEOPS_MCP_ENABLED=false uv run lifeops --mcp-enabled --context`（或等价入口）
      2. 查看启动日志中 MCP enabled 最终值
    Expected Result: CLI 优先级最高
    Evidence: .sisyphus/evidence/task-1-cli-override.txt

- [x] 2. 定义 MCP 类型与命名规范（tool/resource/prompt）

  **What to do**:
  - 定义 MCP tool/resource/prompt 的内部表示（类型/结构）
  - 统一命名为 `mcp.<server>.<tool>` 并禁止覆盖本地工具
  - 约束 ToolParams 严格字段（extra=forbid）

  **Must NOT do**:
  - 不更改现有 ToolDefinition/ToolResult 接口

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: [`coding-standards`]
  - **Skills Evaluated but Omitted**:
    - `api-design`: 非对外 API

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1,3,4,5)
  - **Blocks**: 7,9,10,11
  - **Blocked By**: None

  **References**:
  - `src/lifeops/tools/base.py` — ToolParams/ToolDefinition/ToolResult 约束
  - `src/lifeops/tools/registry.py` — 注册与 execute 机制
  - MCP build client 文档 — https://modelcontextprotocol.io/docs/develop/build-client

  **Acceptance Criteria**:
  - [ ] MCP tool 名称必须带 `mcp.<server>.` 前缀
  - [ ] 若与本地工具重名，拒绝注册并记录 warning

  **QA Scenarios**:
  
  Scenario: MCP 工具命名冲突被拒绝
    Tool: Bash
    Preconditions: 本地存在 `bash` 工具
    Steps:
      1. 注册 MCP 工具名 `bash`
      2. 观察注册失败或被拒绝的日志
    Expected Result: 不覆盖本地工具
    Evidence: .sisyphus/evidence/task-2-name-conflict.txt

  Scenario: MCP 工具命名带前缀
    Tool: Bash
    Preconditions: 注册 GitHub MCP 工具
    Steps:
      1. 启动 lifeops 并列出工具
      2. 查找 `mcp.github.*`
    Expected Result: 所有 MCP 工具有前缀
    Evidence: .sisyphus/evidence/task-2-prefix.txt

- [x] 3. Server Manager：静态注册 + 动态注册 API

  **What to do**:
  - 实现 MCP server 管理器（记录状态、配置、连接句柄）
  - 静态注册：启动时读取 JSON 配置并批量注册
  - 动态注册：提供 Python API（如 `add_mcp_server/remove_mcp_server`）

  **Must NOT do**:
  - 不引入 CLI 命令（仅 Python API）

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: [`coding-standards`]
  - **Skills Evaluated but Omitted**:
    - `api-design`: 非对外 API

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1,2,4,5)
  - **Blocks**: 8,10,11
  - **Blocked By**: None

  **References**:
  - `src/lifeops/agent.py:add_tool()` — 动态注册入口模式
  - `src/lifeops/tools/registry.py` — 注册与执行行为

  **Acceptance Criteria**:
  - [ ] 支持静态 JSON 注册多个 server
  - [ ] 提供 Python API 进行运行时新增/移除

  **QA Scenarios**:
  
  Scenario: 静态注册成功
    Tool: Bash
    Preconditions: 设置 `LIFEOPS_MCP_SERVERS` 为包含 github
    Steps:
      1. 启动 lifeops
      2. 查看工具列表是否包含 `mcp.github.*`
    Expected Result: 静态注册生效
    Evidence: .sisyphus/evidence/task-3-static.txt

  Scenario: 动态注册成功
    Tool: Bash
    Preconditions: lifeops 运行中
    Steps:
      1. 在 REPL 或测试中调用 `add_mcp_server()`
      2. 检查工具列表新增
    Expected Result: 动态注册生效
    Evidence: .sisyphus/evidence/task-3-dynamic.txt

- [x] 4. GitHub MCP Server（Docker stdio）运行模板与环境映射

  **What to do**:
  - 定义默认 GitHub MCP server 的 Docker 启动参数模板
  - 明确 `GITHUB_PERSONAL_ACCESS_TOKEN` 必填
  - 支持可选工具集/只读模式等环境变量透传

  **Must NOT do**:
  - 不内置 token 或硬编码

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: [`coding-standards`]
  - **Skills Evaluated but Omitted**:
    - `api-design`: 非 API 设计

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1,2,3,5)
  - **Blocks**: 11
  - **Blocked By**: None

  **References**:
  - GitHub MCP Server README — https://github.com/github/github-mcp-server
  - GitHub MCP Server config docs — https://github.com/github/github-mcp-server/blob/main/docs/server-configuration.md

  **Acceptance Criteria**:
  - [ ] Docker stdio 命令模板可用
  - [ ] 缺少 token 时有清晰错误提示

  **QA Scenarios**:
  
  Scenario: token 缺失报错
    Tool: Bash
    Preconditions: 未设置 `GITHUB_PERSONAL_ACCESS_TOKEN`
    Steps:
      1. 启动 GitHub MCP server（Docker）
      2. 观察错误信息
    Expected Result: 明确提示 token 缺失
    Evidence: .sisyphus/evidence/task-4-no-token.txt

  Scenario: token 存在启动成功
    Tool: Bash
    Preconditions: 设置有效 token
    Steps:
      1. 启动 Docker stdio server
      2. 检查进程正常运行
    Expected Result: server 正常启动
    Evidence: .sisyphus/evidence/task-4-start.txt

- [x] 5. 更新项目说明（PROJECT.md）与使用指南片段

  **What to do**:
  - 更新 `PROJECT.md` 记录 MCP 集成进展
  - 在 README 或合适位置补充 MCP 使用摘要（保持简短）

  **Must NOT do**:
  - 不引入冗长文档或新的 docs 目录

  **Recommended Agent Profile**:
  - **Category**: `writing`
  - **Skills**: [`writing-plans`]
  - **Skills Evaluated but Omitted**:
    - `article-writing`: 非长文

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1-4)
  - **Blocks**: None
  - **Blocked By**: None

  **References**:
  - `PROJECT.md` — 项目进度记录规范
  - `README.md` — 简要使用说明

  **Acceptance Criteria**:
  - [ ] PROJECT.md 增加 MCP 集成条目
  - [ ] README 简短说明 MCP 用法（≤ 10 行）

  **QA Scenarios**:
  
  Scenario: 文档更新可读
    Tool: Bash
    Preconditions: 文档更新完成
    Steps:
      1. 打开 README 与 PROJECT.md
      2. 检查 MCP 说明是否简短且可用
    Expected Result: 文档更新清晰、无冗长段落
    Evidence: .sisyphus/evidence/task-5-docs.txt

- [x] 6. MCP Client Core（stdio 子进程 + initialize/list/call）

  **What to do**:
  - 实现 stdio 传输连接与 MCP 会话生命周期
  - 支持 initialize/list_tools/list_resources/list_prompts/call_tool
  - 关闭连接与子进程清理

  **Must NOT do**:
  - 不引入 Streamable HTTP（当前仅 stdio）

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: [`coding-standards`]
  - **Skills Evaluated but Omitted**:
    - `backend-patterns`: 非 Web 服务

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 7-9)
  - **Blocks**: 7,9,10,11
  - **Blocked By**: 1

  **References**:
  - MCP client tutorial — https://modelcontextprotocol.io/docs/develop/build-client
  - MCP transports — https://modelcontextprotocol.io/specification/latest/basic/transports

  **Acceptance Criteria**:
  - [ ] MCP session initialize 成功
  - [ ] list_tools/resources/prompts 可返回
  - [ ] call_tool 可返回结果

  **QA Scenarios**:
  
  Scenario: stdio MCP 会话初始化
    Tool: Bash
    Preconditions: MCP server 可启动
    Steps:
      1. 启动 stdio MCP server 子进程
      2. 调用 initialize 并获取版本
    Expected Result: 初始化成功，返回协议版本
    Evidence: .sisyphus/evidence/task-6-init.txt

  Scenario: call_tool 正常工作
    Tool: Bash
    Preconditions: MCP server 提供至少 1 个工具
    Steps:
      1. list_tools 获取工具列表
      2. call_tool 调用其中一个工具
    Expected Result: 返回 ToolResult.success=true
    Evidence: .sisyphus/evidence/task-6-call.txt

- [x] 7. MCP Registry Adapter（映射到 ToolRegistry）

  **What to do**:
  - 将 MCP tool schema 映射为 ToolDefinition
  - 将 MCP call_tool 结果转换为 ToolResult
  - 处理参数校验与命名冲突

  **Must NOT do**:
  - 不改变 ToolRegistry.execute 的签名

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: [`coding-standards`]
  - **Skills Evaluated but Omitted**:
    - `api-design`: 非 API 设计

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 6,8,9)
  - **Blocks**: 9,10,11
  - **Blocked By**: 1,2,6

  **References**:
  - `src/lifeops/tools/registry.py` — register/execute 规范
  - `src/lifeops/tools/base.py` — ToolDefinition/ToolResult
  - MCP tool schema 文档 — https://modelcontextprotocol.io/docs/develop/build-client

  **Acceptance Criteria**:
  - [ ] MCP tools 映射后可在 ToolRegistry 中执行
  - [ ] 参数校验错误返回 ToolResult.success=false

  **QA Scenarios**:
  
  Scenario: MCP tool 可被 ToolRegistry 执行
    Tool: Bash
    Preconditions: MCP tools 已注册
    Steps:
      1. 调用 ToolRegistry.execute("mcp.github.<tool>")
      2. 检查返回 ToolResult
    Expected Result: ToolResult.success=true
    Evidence: .sisyphus/evidence/task-7-exec.txt

  Scenario: 参数校验失败
    Tool: Bash
    Preconditions: MCP tool 需要必填参数
    Steps:
      1. 调用 execute 缺少参数
      2. 查看错误
    Expected Result: success=false 且 error 有提示
    Evidence: .sisyphus/evidence/task-7-validate.txt

- [x] 8. 动态注册 API（Agent/Manager 层）

  **What to do**:
  - 在 Agent 或 Manager 层新增 add/remove MCP server 方法
  - 与 ToolRegistry 交互完成工具注册/解绑

  **Must NOT do**:
  - 不新增 CLI 命令

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: [`coding-standards`]

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 6,7,9)
  - **Blocks**: 11
  - **Blocked By**: 1,3

  **References**:
  - `src/lifeops/agent.py:add_tool()` — 动态注册工具模式
  - `src/lifeops/tools/registry.py` — 工具注册

  **Acceptance Criteria**:
  - [ ] add/remove MCP server 可用
  - [ ] 移除后工具不再可用

  **QA Scenarios**:
  
  Scenario: 动态注册新增工具
    Tool: Bash
    Preconditions: MCP server 可连接
    Steps:
      1. 调用 add_mcp_server
      2. 运行 ToolRegistry.execute
    Expected Result: 新工具可用
    Evidence: .sisyphus/evidence/task-8-add.txt

  Scenario: 动态移除工具
    Tool: Bash
    Preconditions: 已注册 MCP 工具
    Steps:
      1. 调用 remove_mcp_server
      2. 再次执行工具
    Expected Result: 报错或返回 not found
    Evidence: .sisyphus/evidence/task-8-remove.txt

- [x] 9. resources/prompts 支持与命名冲突策略

  **What to do**:
  - 支持 list_resources/list_prompts 的对外暴露方式
  - 资源/提示词通过 MCP Manager API 暴露（不作为 ToolRegistry 工具）
  - 统一命名前缀与冲突处理

  **Must NOT do**:
  - 不改变现有 ToolRegistry 的接口语义

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: [`coding-standards`]

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 6-8)
  - **Blocks**: 10,11
  - **Blocked By**: 6,7

  **References**:
  - MCP client tutorial — https://modelcontextprotocol.io/docs/develop/build-client
  - 当前 ToolRegistry 行为 — `src/lifeops/tools/registry.py`

  **Acceptance Criteria**:
  - [ ] resources/prompts 可被列出并访问（通过 MCP Manager API）
  - [ ] 命名冲突不会覆盖本地工具

  **QA Scenarios**:
  
  Scenario: list_resources 可返回
    Tool: Bash
    Preconditions: MCP server 支持 resources
    Steps:
      1. 通过 MCP Manager API 调用 list_resources
      2. 输出包含至少 1 个资源
    Expected Result: 资源列表可用
    Evidence: .sisyphus/evidence/task-9-resources.txt

  Scenario: list_prompts 可返回
    Tool: Bash
    Preconditions: MCP server 支持 prompts
    Steps:
      1. 通过 MCP Manager API 调用 list_prompts
      2. 输出包含至少 1 个 prompt
    Expected Result: prompt 列表可用
    Evidence: .sisyphus/evidence/task-9-prompts.txt

- [ ] 10. 单元测试（adapter/manager/client）

  **What to do**:
  - 为 MCP Client Core、Adapter、Server Manager 编写单元测试
  - 覆盖参数校验、命名冲突、错误转换

  **Must NOT do**:
  - 不引入新的测试框架

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: [`tdd-workflow`]

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Task 11)
  - **Blocks**: Final Verification
  - **Blocked By**: 1,2,6,7,9

  **References**:
  - `tests/test_tool_registry.py` — ToolRegistry 测试风格
  - `tests/test_builtin_tools.py` — 工具测试风格

  **Acceptance Criteria**:
  - [ ] pytest 通过全部单元测试
  - [ ] 覆盖命名冲突与参数校验

  **QA Scenarios**:
  
  Scenario: 单元测试通过
    Tool: Bash
    Preconditions: 测试实现完成
    Steps:
      1. `uv run pytest tests/test_mcp_*.py -v`
    Expected Result: 全部通过
    Evidence: .sisyphus/evidence/task-10-unit.txt

- [ ] 11. 集成测试（启动 MCP server 走完整链路）

  **What to do**:
  - 模拟或启动 GitHub MCP Server（Docker stdio）
  - 覆盖完整链路：initialize → list_tools → call_tool

  **Must NOT do**:
  - 不依赖真实 GitHub 账号操作（可用只读/最小工具集）

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: [`tdd-workflow`]

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Task 10)
  - **Blocks**: Final Verification
  - **Blocked By**: 1,3,4,6,7,8,9,10

  **References**:
  - GitHub MCP Server docs — https://github.com/github/github-mcp-server
  - MCP client tutorial — https://modelcontextprotocol.io/docs/develop/build-client

  **Acceptance Criteria**:
  - [ ] 完整链路测试通过
  - [ ] 不需要真实写权限（只读）

  **QA Scenarios**:
  
  Scenario: 集成测试通过
    Tool: Bash
    Preconditions: Docker 可用，设置 token
    Steps:
      1. 启动 GitHub MCP server
      2. 运行集成测试
    Expected Result: 全部通过
    Evidence: .sisyphus/evidence/task-11-integration.txt

---

## Final Verification Wave

- [ ] F1. **Plan Compliance Audit** — `oracle`
- [ ] F2. **Code Quality Review** — `unspecified-high`
- [ ] F3. **Real Manual QA** — `unspecified-high`
- [ ] F4. **Scope Fidelity Check** — `deep`

---

## Commit Strategy

- **1**: `feat(mcp): add client core and registry adapter`
- **2**: `test(mcp): add unit and integration tests`
- **3**: `docs(project): update PROJECT.md`

---

## Success Criteria

### Verification Commands
```bash
uv run pytest tests/ -v  # Expected: all pass
uv run ruff check src/ tests/  # Expected: no issues
```

### Final Checklist
- [ ] MCP tools/resources/prompts 可用
- [ ] GitHub MCP Server stdio Docker 可连接
- [ ] 多 server 静态 JSON + 动态 API 可用
- [ ] 无新增独立配置文件
- [ ] 测试通过
