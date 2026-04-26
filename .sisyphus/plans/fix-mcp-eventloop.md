# 修复 MCP 工具调用的事件循环隔离问题

## TL;DR

> **Quick Summary**: `agent.py` 的 `main()` 函数中，MCP 连接和 REPL 分别用两个 `asyncio.run()` 调用，导致 MCP 的 `ClientSession` 和 anyio 流绑定在事件循环 A 上，而工具调用发生在事件循环 B 中，触发 `Future attached to a different loop` 错误。合并为单个 `asyncio.run()` 即可修复。
>
> **Deliverables**:
> - 修复 `agent.py` 中的事件循环隔离 bug
> - MCP 工具调用恢复正常（如 `mcp.github.get_me`）
>
> **Estimated Effort**: Quick（单文件改动）
> **Parallel Execution**: 不适用（单任务）

---

## Context

### 根因分析

在 `src/lifeops/agent.py` 的 `main()` 函数中（第 270-279 行）：

```python
# 第一个 asyncio.run() → 创建事件循环 A
asyncio.run(agent.mcp_manager.connect_and_register_all(agent.tools))

# 第二个 asyncio.run() → 创建事件循环 B
asyncio.run(_run_repl(agent))
```

`asyncio.run()` 每次调用都会创建**新的事件循环**。MCP 客户端的 `ClientSession`、anyio 内存流、后台 I/O 任务都创建在事件循环 A 中。当 REPL 中触发工具调用时，`client.call_tool()` 尝试使用事件循环 A 的资源，但代码运行在事件循环 B 中，导致：

```
Future <Future pending> attached to a different loop
```

随后错误处理中的 `_cleanup()` 清空了 `_session`，重试时报 `MCP client 'github' 未连接`。

### 相关代码

- **`agent.py:270-279`** — `main()` 函数中的两个独立 `asyncio.run()` 调用
- **`agent.py:282-329`** — `_run_repl()` 函数，REPL 主循环
- **`tools/mcp/client.py:58-86`** — `MCPClient.connect()`，创建 ClientSession 和 I/O 任务

---

## Work Objectives

### Core Objective
修复 MCP 工具调用时的事件循环隔离问题，使 `agent.py` 中 MCP 连接和 REPL 运行在同一个事件循环中。

### Concrete Deliverables
- `src/lifeops/agent.py` — 修改 `main()` 函数

### Must Have
- MCP 连接和工具调用使用同一事件循环
- 启动日志正常打印 MCP 连接状态
- 修复后 `mcp.github.get_me` 可正常调用

### Must NOT Have
- 不改变 REPL 功能和行为
- 不修改 MCP 核心库代码（client.py、manager.py、adapter.py）

---

## Verification Strategy

### Test Decision
- **基础设施**: pytest 已配置
- **自动化测试**: 手动验证（此问题为运行时事件循环问题，需实际启动验证）
- **Agent-Executed QA**: 手动启动 LifeOps 并调用一个 MCP 工具验收

---

## Execution Strategy

### 单任务修复（无并行需求）

```
Task 1: 修改 agent.py main() 函数
```

---

## TODOs

- [ ] 1. 修改 `agent.py`——合并 `asyncio.run()` 为单事件循环

  **What to do**:
  1. 删除 `main()` 函数中的第一个 `asyncio.run(agent.mcp_manager.connect_and_register_all(agent.tools))` 及其后的 console.print
  2. 将最后的 `asyncio.run(_run_repl(agent))` 替换为 `asyncio.run(_start(agent))`
  3. 新增 `async def _start(agent: Agent) -> None` 函数：
     - 在同一个事件循环中先执行 MCP 连接
     - 连接成功后打印状态信息
     - 然后执行 `_run_repl(agent)`

  具体变更：

  **删除的代码**（`main()` 中第 270-272 行）：
  ```python
  if config.mcp.enabled and config.mcp.servers.strip():
      asyncio.run(agent.mcp_manager.connect_and_register_all(agent.tools))
      console.print(f"[dim]MCP: 已连接 {len(agent.mcp_manager.list_servers())} 个服务器[/dim]\n")
  ```

  **替换的代码**（`main()` 最后一行）：
  ```python
  # 原来:
  asyncio.run(_run_repl(agent))
  # 改为:
  asyncio.run(_start(agent))
  ```

  **新增的异步函数**（放在 `_run_repl` 之前或之后）：
  ```python
  async def _start(agent: Agent) -> None:
      """连接 MCP 并启动 REPL（共享同一事件循环）。"""
      from rich.console import Console

      if agent.config.mcp.enabled and agent.config.mcp.servers.strip():
          try:
              await agent.mcp_manager.connect_and_register_all(agent.tools)
              Console().print(
                  f"[dim]MCP: 已连接 {len(agent.mcp_manager.list_servers())} 个服务器[/dim]\n"
              )
          except Exception:
              logger.exception("MCP 连接失败")

      await _run_repl(agent)
  ```

  **Must NOT do**:
  - 不改动 `_run_repl` 函数本身
  - 不改动 MCP client/manager/adapter 代码
  - 不引入新的依赖

  **References**:
  - `agent.py:268-279` — 当前 `main()` 函数尾部
  - `agent.py:282-329` — `_run_repl()` 函数定义
  - `tools/mcp/client.py:58-86` — `MCPClient.connect()` 中的事件循环绑定点

  **QA Scenarios**:
  ```text
  Scenario: MCP 工具调用正常
    前提: GitHub token 已配置、MCP server 配置正确
    步骤:
      1. 启动 LifeOps: uv run lifeops
      2. 在 REPL 中输入: 查看当前 GitHub 用户信息
      3. 观察是否调用 mcp.github.get_me 工具
    预期结果: 成功返回 GitHub 用户信息（用户名、邮箱等），无事件循环报错
    失败指标: 出现 "attached to a different loop" 或 "MCP client 未连接" 错误
  ```

  **Evidence**:
  - 控制台输出截图显示正常返回用户信息

  **Commit**: YES
  - Message: `fix(agent): 合并 main() 中的 asyncio.run() 为单事件循环修复 MCP 工具调用`
  - Files: `src/lifeops/agent.py`

---

## Success Criteria

### 验证命令
```bash
# 启动 LifeOps
uv run lifeops

# 在 REPL 中测试
You: 查看我 GitHub 上的仓库列表
# 期望: 正常返回仓库信息，无事件循环错误
```

### 最终检查
- [ ] 启动时 MCP 连接日志正常
- [ ] 调用 `mcp.github.get_me` 返回正确结果
- [ ] 多次调用 MCP 工具不会出现 event loop 错误
