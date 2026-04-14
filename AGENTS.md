# AGENTS.md — LifeOps

## 回答风格

- 始终用中文回答，写入文档文件也以中文为主

## 命令

```bash
uv sync                          # 安装依赖
uv run lifeops                   # 运行 Agent REPL
uv run pytest tests/ -v          # 运行全部测试 (48)
uv run pytest tests/test_agent.py::test_name -v  # 运行单个测试
uv run ruff check src/ tests/    # 代码检查（未配置格式化工具）
```

## 架构

- 入口: `lifeops.agent:main` → REPL 循环，每次输入调用 `Agent.run()`
- ReAct 模式: 用户输入 → LLM → 工具调用 → 迭代 → 最终响应（最多 10 轮）
- 上下文分层: L1（始终在上下文中：系统提示、近期历史）→ L2（按需加载：Skill 文档、RAG）→ L3（溢出层：工具结果，满时压缩）
- 配置: `core/config.py` 使用 pydantic-settings；优先级为 环境变量 > `.env` 文件 > `configs/default.yaml`

## 关键约定

- 每开发或改动一个功能更新项目说明文档 `PROJECT.md`
- **包布局**: 源码在 `src/lifeops/`，测试在 `tests/`，hatch 从 `src/lifeops` 构建
- **`LLM_API_KEY` 为必填** — CLI 未设置时直接退出
- 环境变量前缀: `LLM_` 用于 LLM 配置，`LIFEOPS_` 用于顶层配置，`LIFEOPS_CONTEXT_` 用于上下文配置
- 测试使用 `pytest-asyncio`，`asyncio_mode = "auto"` — 直接写 `async def test_...`，无需装饰器
- `conftest.py` 中 fixture 通过环境变量设置 `LLM_API_KEY=test-key`
- Ruff: line-length 100，target Python 3.13
- `.python-version` 为 3.13；`pyproject.toml` 要求 `>=3.12`