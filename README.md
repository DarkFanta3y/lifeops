<div align="center">

# LifeOps

**AI 驱动的生活助手智能体**

[![Python](https://img.shields.io/badge/Python-3.12%2B-blue.svg)](https://python.org)
[![uv](https://img.shields.io/badge/uv-package_manager-6E39C6.svg)](https://github.com/astral-sh/uv)
[![pytest](https://img.shields.io/badge/tests-48%20passed-green.svg)](https://docs.pytest.org)
[![Ruff](https://img.shields.io/badge/linter-ruff-FCC624.svg)](https://docs.astral.sh/ruff/)

[English](#features) · [快速开始](#快速开始) · [架构](#架构) · [配置](#配置) · [开发](#开发)

</div>

---

## Features

- **ReAct 模式** — 推理与行动交替迭代，最多 10 轮自动完成复杂任务
- **三层上下文管理** — L1 常驻 / L2 按需 / L3 溢出压缩，高效利用 200K token 窗口
- **工具系统** — 内置 Bash、文件读写、网络搜索，支持动态注册自定义工具
- **OpenAI 兼容** — 支持 GPT-4o / Claude / 本地模型，一行配置切换后端
- **Rich CLI** — 彩色终端界面，内置 `reset` / `context` 命令

## 快速开始

```bash
# 安装依赖
uv sync

# 设置 API Key
export LLM_API_KEY=your-key-here

# 启动
uv run lifeops
```

启动后进入交互式 REPL：

```
╭─────────────────────────────╮
│  LifeOps Agent v0.1.0       │
╰─────────────────────────────╯
You: 今天天气怎么样？
Thinking...
╭─────────────────────────────╮
│  Agent                       │
│  今天上海天气...              │
╰─────────────────────────────╯
```

内置命令：
- `reset` — 清除对话历史
- `context` — 查看上下文 token 用量
- `exit` / `quit` — 退出

## 架构

```
                  ┌──────────────┐
    用户输入 ───► │   Agent      │
                  │  (ReAct 循环) │
                  └──────┬───────┘
                         │
            ┌────────────┼────────────┐
            ▼            ▼            ▼
     ┌──────────┐ ┌──────────┐ ┌──────────┐
     │   LLM    │ │  Tools   │ │ Context  │
     │  Client  │ │ Registry │ │ Manager  │
     └──────────┘ └──────────┘ └──────────┘
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
               ┌──────┐      ┌──────────┐    ┌──────────┐
               │  L1  │      │   L2     │    │   L3     │
               │ 常驻  │      │  按需加载 │    │ 溢出压缩 │
               └──────┘      └──────────┘    └──────────┘
```

**核心流程**: 用户输入 → LLM 推理 → 工具调用 → 迭代 → 最终响应

**上下文分层**:
- **L1** — 系统提示、Skill 目录、近期对话，始终在上下文中
- **L2** — Skill 完整文档、RAG 检索结果，按需加载
- **L3** — 工具执行结果，容量不足时自动压缩

## 配置

优先级: 环境变量 > `.env` 文件 > `configs/default.yaml`

### 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `LLM_API_KEY` | LLM API 密钥（**必填**） | — |
| `LLM_MODEL` | 模型名称 | `gpt-4o` |
| `LLM_API_BASE` | API 地址 | `https://api.openai.com/v1` |
| `LIFEOPS_DEBUG` | 调试模式 | `false` |
| `LIFEOPS_LOG_LEVEL` | 日志级别 | `INFO` |

### 上下文调优

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `LIFEOPS_CONTEXT_MAX_CONTEXT_TOKENS` | 上下文窗口大小 | `200000` |
| `LIFEOPS_CONTEXT_L1_BUDGET_RATIO` | L1 预算占比 | `0.10` |
| `LIFEOPS_CONTEXT_L2_BUDGET_RATIO` | L2 预算占比 | `0.60` |
| `LIFEOPS_CONTEXT_L3_BUDGET_RATIO` | L3 预算占比 | `0.20` |

## 项目结构

```
src/lifeops/
├── agent.py                # 主类 + CLI 入口
├── core/
│   ├── config.py           # 配置管理 (pydantic-settings)
│   └── context_manager.py  # 三层上下文管理器
├── llm/
│   ├── client.py           # OpenAI 兼容 LLM 客户端
│   └── types.py             # Message, ToolCallResult 等类型
├── tools/
│   ├── base.py              # Tool 基类与 ToolDefinition
│   ├── registry.py          # 工具注册中心
│   └── builtin/             # 内置工具
│       ├── bash.py
│       ├── file_read.py
│       ├── file_edit.py
│       └── web_search.py
└── utils/
    └── logging.py           # 日志工具

tests/
├── conftest.py              # 公共 fixture
├── test_agent.py
├── test_builtin_tools.py
├── test_context_manager.py
├── test_llm_client.py
└── test_tool_registry.py
```

## 开发

```bash
# 安装开发依赖
uv sync

# 运行测试
uv run pytest tests/ -v

# 运行单个测试
uv run pytest tests/test_agent.py::test_agent_initialization -v

# 代码检查
uv run ruff check src/ tests/
```

测试使用 `pytest-asyncio`，`asyncio_mode = "auto"`，直接写 `async def test_...` 即可。

## Roadmap

- [x] **Phase 1** — Agent 核心 + Tool 系统
- [ ] **Phase 2** — Skill 系统（发现、匹配、加载）
- [ ] **Phase 3** — Memory 系统（STM / LTM / Working Memory）
- [ ] **Phase 4** — RAG 系统（文档向量化、语义检索）
- [ ] **Phase 5** — MCP 集成（Stdio / HTTP / SSE）

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=DarkFanta3y/lifeops&type=Date)](https://star-history.com/#DarkFanta3y/lifeops&Date)

## License

MIT