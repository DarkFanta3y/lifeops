# LifeOps 项目进度

## 概述

LifeOps 是一个 AI 驱动的生活助手智能体，基于 ReAct (Reasoning + Acting) 模式设计。当前阶段聚焦通用 Agent 框架，后续再拓展生活场景 Skill。

## 技术栈

- **语言**: Python 3.12+
- **包管理**: uv
- **LLM**: 智谱 BigModel OpenAI 兼容接口 (默认 glm-4-flash, 支持 GPT-4o / Claude / 本地模型)
- **向量数据库**: ChromaDB (Phase 3)
- **测试**: pytest + pytest-asyncio
- **Lint**: ruff

## 完成进度

### Phase 1: Agent 核心 + Tool 系统 ✅

| Task | 状态 | 说明 |
|------|------|------|
| 项目脚手架 (uv + 配置) | ✅ | pyproject.toml, uv 环境, 配置管理, 日志 |
| LLM 客户端 | ✅ | OpenAI 兼容接口, tool calling 支持 |
| Tool 基类 + 注册中心 + 内置工具 | ✅ | bash, file_read, file_edit, web_search(占位) |
| 上下文管理器 | ✅ | L1/L2/L3 三层, token 预算, 压缩策略 |
| Agent 主循环 (ReAct) | ✅ | 用户输入 → LLM → 工具调用 → 迭代 → 输出 |
| CLI REPL 入口 | ✅ | Rich 界面, reset/context 命令 |

**测试覆盖**: 48 个测试全部通过, ruff lint 无错误

### Phase 2: Skill 系统 (待开发)

- Skill 发现: 扫描目录, 解析 SKILL.md 元数据
- Skill 匹配: description 隐式语义匹配 (score > threshold)
- Skill 加载: L2 加载完整 SKILL.md, L3 按需加载引用

### Phase 3: Memory 系统 (待开发)

- STM: 对话窗口中的短期记忆
- LTM: ChromaDB 向量存储与检索
- Working Memory: 任务进行中的临时状态
- 记忆衰减: TTL + 相似度衰减

### Phase 4: RAG 系统 (待开发)

- 文档分块与向量化
- ChromaDB 索引管理
- 语义检索 + 重排

### Phase 5: MCP 集成 🔧

| Task | 状态 | 说明 |
|------|------|------|
| MCP Client Core | ✅ | stdio 传输、生命周期管理、工具发现与调用 |
| GitHub MCP Server 接入 | ✅ | Docker stdio 模式，需 GITHUB_PERSONAL_ACCESS_TOKEN |
| 多 Server 注册机制 | ✅ | 支持 CLI/ENV/JSON 三种配置方式动态注册 MCP Server |
| 配置方式 | ✅ | CLI 参数（`--mcp-enabled`/`--mcp-disabled`/`--mcp-servers`）、环境变量（`LIFEOPS_MCP_ENABLED`/`LIFEOPS_MCP_SERVERS`）、JSON 配置文件 |
| 资源与提示暴露 | ✅ | MCP 资源/提示通过 Manager API 暴露，不混入 ToolRegistry |
| 健康检查与降级 | 待开发 | Server 连接状态检测、自动降级 |

## 文件结构

```
lifeops/
├── pyproject.toml
├── src/lifeops/
│   ├── __init__.py
│   ├── agent.py                   # Agent 主类 + CLI 入口
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── client.py              # LLM 客户端
│   │   └── types.py               # Message, ChatResponse, ToolCallResult
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py              # 配置管理 (env + 默认值)
│   │   └── context_manager.py     # 上下文窗口管理 (L1/L2/L3)
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── base.py                # Tool 基类
│   │   ├── registry.py            # 工具注册中心
│   │   └── builtin/
│   │       ├── __init__.py
│   │       ├── bash.py
│   │       ├── file_read.py
│   │       ├── file_edit.py
│   │       └── web_search.py
│   └── utils/
│       ├── __init__.py
│       └── logging.py
├── tests/
│   ├── conftest.py
│   ├── test_agent.py
│   ├── test_builtin_tools.py
│   ├── test_context_manager.py
│   ├── test_llm_client.py
│   └── test_tool_registry.py
└── docs/
    ├── architecture.md
    ├── fast_start.md
    ├── GUIDE.md
    └── api.md
```

## 运行方式

```bash
# 安装依赖
uv sync

# 设置 API Key
export LLM_API_KEY=your-key-here

# 运行
uv run lifeops

# 或指定配置
uv run python -m lifeops.agent

# 运行测试
uv run pytest tests/ -v

# 代码检查
uv run ruff check src/ tests/
```

## 配置

配置优先级: 环境变量 > .env 文件 > 默认值

| 环境变量 | 说明 | 默认值 |
|---------|------|--------|
| LLM_API_KEY | LLM API密钥 | - |
| LLM_MODEL | 模型名称 | glm-4-flash |
| LLM_API_BASE | API地址 | https://open.bigmodel.cn/api/paas/v4 |
| LLM_TIMEOUT | 请求超时(秒) | 60 |
| LIFEOPS_DEBUG | 调试模式 | false |
| LIFEOPS_LOG_LEVEL | 日志级别 | INFO |