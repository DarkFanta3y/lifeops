# Web Search (SerpApi) 实现 + Tool Schema 系统重构

## TL;DR

> **核心目标**: 用 Pydantic BaseModel 重构工具参数定义系统，实现标准 Function Calling 格式的 tool schema，然后基于新系统实现 SerpApi 网页搜索工具。
> 
> **交付物**:
> - 重构后的 `base.py` + `registry.py` + 3 个内置工具 — Pydantic 模型参数系统（原子提交）
> - `web_search.py` — SerpApi 搜索实现（闭包模式，Client 复用）
> - `SerpApiConfig` 配置 + `.env` 更新
> - 完整测试覆盖
> 
> **预估工作量**: Medium
> **并行执行**: YES — 3 个波次
> **关键路径**: Task 1 (Pydantic 系统原子重构) → Task 4 (web_search 实现) → Task 6 (集成验证)

---

## Context

### 原始需求
用户要求实现 `web_search` 工具，使用 SerpApi（通过 `serpapi` Python 包），并提供 API Key。同时要求为本项目的工具设置标准 Function Calling 格式的 tool schema，让大模型能理解可用工具。

### 讨论摘要
- **Tool Schema 系统**: 选择 Pydantic BaseModel 定义参数 → 自动生成 JSON Schema（类型安全、IDE 友好、与项目现有 Pydantic 生态一致）
- **SerpApi 配置**: 在 config.py 中新增 `SerpApiConfig`，通过 `SERPAPI_API_KEY` 环境变量读取，遵循项目现有模式
- **搜索参数**: query（必填）+ num_results, location, language（可选，默认 zh-cn 匹配项目中文环境）
- **测试策略**: mock 单元测试 + 标记为 slow 的集成测试

### Metis 审查
**发现的关键问题**（已解决）:
- ⚠️ `google-search-results` 包已弃用 → 改用 `serpapi` 包（pip install serpapi）
- 新包 API: `serpapi.Client(api_key=...)` 而非 `GoogleSearch(dict)`
- 无原生异步支持 → 需用 `asyncio.to_thread()` 包装
- API Key 必须显式传入，不会自动读环境变量

### Momus 审查（第二轮）
**发现并修复的问题**:
1. 🔴 **Task 1/4 必须合并** — 不能在移除 ToolParameter 后让 bash/file_read/file_edit 仍导入它，否则中间态编译失败
2. 🔴 **API Key 泄露风险** — 计划文件不应包含真实 API Key
3. 🟡 **`register_all_builtin_tools` 签名变更** — config 参数应有 `None` 默认值，避免破坏现有调用方
4. 🟡 **SerpApi 异常处理不完整** — 需要捕获 `APIKeyNotProvided`、`HTTPConnectionError`、`SerpApiError` 基类
5. 🟢 **Client 复用** — SerpApi Client 应在 `create_web_search_tool` 中创建一次，闭包捕获复用

---

## Work Objectives

### 核心目标
建立 Pydantic 驱动的工具参数系统，实现标准 Function Calling 格式 schema，并基于此系统完成 SerpApi 网页搜索工具。

### 具体交付物
- `src/lifeops/tools/base.py` — 用 Pydantic BaseModel 替代 dataclass ToolParameter
- `src/lifeops/tools/registry.py` — 基于 Pydantic model_json_schema() 生成 tool schema
- `src/lifeops/tools/builtin/bash.py` — 迁移到 Pydantic 参数模型
- `src/lifeops/tools/builtin/file_read.py` — 迁移到 Pydantic 参数模型
- `src/lifeops/tools/builtin/file_edit.py` — 迁移到 Pydantic 参数模型
- `src/lifeops/core/config.py` — 新增 SerpApiConfig
- `src/lifeops/tools/builtin/web_search.py` — SerpApi 搜索实现（闭包模式）
- `src/lifeops/tools/builtin/__init__.py` — 更新注册函数签名（config 可选）
- `src/lifeops/agent.py` — 传入 config
- `pyproject.toml` — 新增 serpapi 依赖 + pytest slow marker
- `.env` + `.env.example` — 新增 SERPAPI_API_KEY
- `tests/` — 完整测试覆盖

### Definition of Done
- [ ] `uv run pytest tests/ -v -m "not slow"` 全部通过
- [ ] `uv run ruff check src/ tests/` 无错误
- [ ] schema 输出命令验证 Function Calling 格式:
  ```bash
  uv run python -c "from lifeops.tools import ToolRegistry; from lifeops.tools.builtin import register_all_builtin_tools; from lifeops.core.config import AppConfig; r = ToolRegistry(); c = AppConfig(); register_all_builtin_tools(r, c); schemas = r.get_openai_tool_schemas(); ws = [s for s in schemas if s['function']['name'] == 'web_search'][0]; print(ws)"
  ```
- [ ] web_search 工具可成功调用 SerpApi 并返回格式化结果
- [ ] API Key 缺失时优雅降级（返回友好错误而非崩溃）

### Must Have
- Pydantic BaseModel 参数系统替换现有 ToolParameter dataclass（**原子提交，与 3 个内置工具迁移一起**）
- `model_json_schema()` 自动生成标准 JSON Schema
- web_search 使用 serpapi 包实现真实搜索（闭包模式复用 Client）
- SerpApiConfig 遵循项目配置模式（pydantic-settings + 环境变量）
- `register_all_builtin_tools` 的 config 参数可选（None 默认值），不破坏现有调用方
- 完整的 SerpApi 异常处理层级：`APIKeyNotProvided` → `TimeoutError` → `HTTPError` → `SerpApiError`
- mock 单元测试 + slow 集成测试

### Must NOT Have (Guardrails)
- ❌ 不在代码或计划文件中硬编码 API Key（只在 .env 中配置，.env 已在 .gitignore）
- ❌ 不使用已弃用的 `google-search-results` 包，必须用 `serpapi`
- ❌ 不破坏现有的 `get_openai_tool_schemas()` 输出格式（向后兼容）
- ❌ 不在没有 API Key 时让 agent 崩溃（要优雅处理）
- ❌ 不在 handler 中直接同步阻塞调用（必须用 asyncio.to_thread 包装）
- ❌ 不添加不必要的搜索参数（如设备类型、Google 域名等高级选项）
- ❌ 不分开提交 ToolParameter 移除和工具迁移（必须原子提交）
- ❌ AI slop 防护: 不添加过度注释、不创建过多的抽象层、不引入不需要的中间件模式

---

## Verification Strategy (MANDATORY)

> **零人工干预** — 所有验证由代理执行。不接受需要"用户手动测试/确认"的验收标准。

### 测试决策
- **已有基础设施**: YES (pytest + pytest-asyncio)
- **自动化测试**: YES (TDD 模式: 先写失败测试 → 最小实现 → 重构)
- **框架**: pytest + pytest-asyncio (项目已有)
- **TDD 流程**: 每个 Task 遵循 RED → GREEN → REFACTOR

### QA 策略
每个 Task 必须包含代理执行的 QA 场景。
证据保存到 `.sisyphus/evidence/task-{N}-{scenario-slug}.{ext}`。

- **API/后端**: 使用 Bash (curl) — 发送请求，断言 status + response 字段
- **库/模块**: 使用 Bash (uv run python -c) — 导入、调用函数、比较输出

---

## Execution Strategy

### 并行执行波次

```
Wave 1 (立即开始 — 基础设施，可并行):
├── Task 1: Pydantic 参数系统 + 迁移所有内置工具（原子提交）[unspecified-high]
├── Task 2: 添加 serpapi 依赖 + SerpApiConfig 配置 [quick]
└── Task 3: 添加 pytest slow marker 配置 [quick]

Wave 2 (Wave 1 完成后 — 实现):
├── Task 4: 实现 web_search SerpApi 搜索工具（闭包模式）[deep]
└── Task 5: web_search 完整测试套件（mock + 集成）[unspecified-high]

Wave 3 (Wave 2 完成后 — 验证):
└── Task 6: 端到端集成验证 [quick]

关键路径: Task 1 → Task 4 → Task 6
并行加速: ~35% 比顺序执行
最大并发: 3 (Wave 1)
```

### 依赖矩阵

| Task | 依赖 | 被依赖 |
|------|------|--------|
| 1 | — | 4, 5 |
| 2 | — | 4, 5 |
| 3 | — | 5 |
| 4 | 1, 2 | 5, 6 |
| 5 | 1, 2, 3, 4 | 6 |
| 6 | 4, 5 | — |

### 代理分派摘要

- **Wave 1**: 3 tasks — T1 `unspecified-high`, T2 `quick`, T3 `quick`
- **Wave 2**: 2 tasks — T4 `deep`, T5 `unspecified-high`
- **Wave 3**: 1 task — T6 `quick`

---

## TODOs

- [x] 1. Pydantic 参数系统 + 迁移所有内置工具（原子提交）

  **What to do**:
  - ⚠️ **此任务必须原子完成** — base.py/registry.py 重构 + bash/file_read/file_edit 迁移在同一个提交中，确保中间态不出现编译失败
  - 在 `src/lifeops/tools/base.py` 中:
    - 定义 `ToolParams(BaseModel)` 空基类（用于类型约束）
    - 将 `ToolDefinition` 的 `parameters: list[ToolParameter]` 替换为 `parameters_model: type[ToolParams]`
    - 移除 `ToolParameter` dataclass
  - 在 `src/lifeops/tools/registry.py` 中:
    - `get_openai_tool_schemas()` 使用 `parameters_model.model_json_schema()` 生成标准 JSON Schema
    - `_validate_params()` 使用 `parameters_model.model_validate(params)` 验证参数
  - 为每个内置工具定义 Pydantic 参数模型:
    - `BashParams`: `command: str`, `timeout: int = 30`, `workdir: str | None = None`
    - `FileReadParams`: `path: str`, `encoding: str = "utf-8"`
    - `FileEditParams`: `path: str`, `operation: Literal["create", "replace", "append"]`, `content: str | None = None`, `old_text: str | None = None`, `new_text: str | None = None`
  - 更新每个工具的 `create_*_tool` 函数使用 `parameters_model=XXXParams`
  - 更新 handler 函数使用 params_model 验证替代手动参数提取
  - 确保 `get_openai_tool_schemas()` 输出格式与之前兼容（`type: "function"`, `function: {name, description, parameters: {type: "object", properties, required}}`）
  - **TDD**: 先写 schema 生成测试 → 实现系统 → 验证所有工具测试通过

  **Must NOT do**:
  - ❌ 不分开提交 ToolParameter 移除和工具迁移（必须原子提交）
  - ❌ 不破坏 `get_openai_tool_schemas()` 的返回类型（仍为 `list[dict]`）
  - ❌ 不删除 `ToolResult` dataclass（仍需要）
  - ❌ 不引入额外的抽象层或中间件

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: 5 个文件的原子重构，需要确保中间态一致
  - **Skills**: [`backend-patterns`]
    - `backend-patterns`: Pydantic 模型设计和参数验证模式

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 2, 3)
  - **Blocks**: Tasks 4, 5
  - **Blocked By**: None

  **References**:

  **Pattern References** (existing code to follow):
  - `src/lifeops/core/config.py:32-45` — Pydantic Settings 模式: `LLMConfig` 展示了项目中使用 pydantic-settings 的配置定义模式，新 `ToolParams` 应保持同样的 Field 风格
  - `src/lifeops/tools/base.py:11-16` — `ToolParameter` dataclass: 当前参数定义方式（被替代目标）
  - `src/lifeops/tools/registry.py:56-79` — `get_openai_tool_schemas()`: 当前手动构建 schema 的逻辑，需改为 `model_json_schema()`
  - `src/lifeops/tools/builtin/bash.py:10-51` — bash handler: 最简单的工具迁移模板
  - `src/lifeops/tools/builtin/file_edit.py` — file_edit: `operation` 参数需要 `Literal` 类型约束

  **Test References**:
  - `tests/test_tool_registry.py` — schema 生成测试
  - `tests/test_builtin_tools.py` — 所有内置工具的回归测试

  **WHY Each Reference Matters**:
  - config.py 展示项目中的 Pydantic 使用惯例
  - base.py 的 ToolParameter 是被替代的核心，移除后需确保所有引用都更新
  - registry.py 的 schema 生成是核心变更，必须保持 OpenAI Function Calling 格式兼容
  - bash.py 是最简单的迁移模板，其他工具复制此模式

  **Acceptance Criteria**:

  **If TDD**:
  - [ ] `uv run pytest tests/test_tool_registry.py -v` → PASS
  - [ ] `uv run pytest tests/test_builtin_tools.py -v` → 所有现有测试 PASS（除了 web_search placeholder 测试需更新）
  - [ ] ToolParameter 类名不再存在于任何源码中

  **QA Scenarios**:

  ```
  Scenario: Pydantic 模型自动生成标准 JSON Schema
    Tool: Bash (uv run python -c)
    Preconditions: 新的 ToolDefinition 使用 parameters_model
    Steps:
      1. 运行: uv run python -c "from lifeops.tools import ToolRegistry; from lifeops.tools.builtin import register_all_builtin_tools; r = ToolRegistry(); register_all_builtin_tools(r); schemas = r.get_openai_tool_schemas(); print(schemas)"
      2. 验证每个 schema 包含 "type": "function", "function" 对象, "parameters" 对象
      3. 验证 "parameters" 包含 "properties", "required" 字段
    Expected Result: Schema 输出为标准 OpenAI Function Calling 格式
    Failure Indicators: 缺少字段或类型不对
    Evidence: .sisyphus/evidence/task-1-schema-generation.txt

  Scenario: 旧 ToolParameter dataclass 完全移除
    Tool: Bash
    Steps:
      1. grep -r "ToolParameter" src/lifeops/ — 应返回 0 结果
      2. uv run pytest tests/ -v — 全部通过
    Expected Result: ToolParameter 不存在于源码，所有测试通过
    Failure Indicators: 仍有引用或测试失败
    Evidence: .sisyphus/evidence/task-1-toolparameter-removal.txt

  Scenario: 工具仍然可以正常执行
    Tool: Bash
    Steps:
      1. uv run python -c "from lifeops.tools import ToolRegistry; from lifeops.tools.builtin import register_all_builtin_tools; import asyncio; r = ToolRegistry(); register_all_builtin_tools(r); result = asyncio.run(r.execute('bash', {'command': 'echo hello'})); print(result)"
      2. 验证返回 success=True, output 包含 "hello"
    Expected Result: bash 工具仍返回正确结果
    Failure Indicators: 任何工具返回错误
    Evidence: .sisyphus/evidence/task-1-tool-execution.txt

  Scenario: 参数验证拒绝无效参数
    Tool: Bash
    Steps:
      1. uv run python -c "from lifeops.tools import ToolRegistry; from lifeops.tools.builtin import register_all_builtin_tools; import asyncio; r = ToolRegistry(); register_all_builtin_tools(r); result = asyncio.run(r.execute('bash', {})); print(result)"
      2. 验证缺少必填参数时返回错误
    Expected Result: 缺少 command 参数时提示错误
    Failure Indicators: 工具静默接受缺少参数的调用
    Evidence: .sisyphus/evidence/task-1-param-validation.txt
  ```

  **Commit**: YES
  - Message: `refactor(tools): replace ToolParameter with Pydantic BaseModel schema system, migrate all tools`
  - Files: `src/lifeops/tools/base.py`, `src/lifeops/tools/registry.py`, `src/lifeops/tools/builtin/bash.py`, `src/lifeops/tools/builtin/file_read.py`, `src/lifeops/tools/builtin/file_edit.py`
  - Pre-commit: `uv run pytest tests/test_tool_registry.py tests/test_builtin_tools.py -v`

- [x] 2. 添加 serpapi 依赖 + SerpApiConfig 配置

  **What to do**:
  - 在 `pyproject.toml` 的 `dependencies` 中添加 `"serpapi>=1.0.0"`
  - 运行 `uv sync` 安装依赖
  - 在 `src/lifeops/core/config.py` 中添加 `SerpApiConfig` 类（继承 `BaseSettings`）:
    - 字段: `api_key: str = ""`, 环境变量前缀 `SERPAPI_`
    - 遵循项目现有 `LLMConfig` 模式
  - 在 `AppConfig` 中添加 `serpapi: SerpApiConfig = Field(default_factory=SerpApiConfig)`
  - 更新 `.env` 添加 `SERPAPI_API_KEY=<用户的 API Key>`
  - 更新 `.env.example` 添加 `SERPAPI_API_KEY=`（空值）
  - **TDD**: 先写配置读取测试

  **Must NOT do**:
  - ❌ 不在源代码或计划文件中硬编码 API Key（只在 `.env` 中）
  - ❌ 不使用 `google-search-results` 包（已弃用）

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 依赖添加 + 配置文件修改，模式明确
  - **Skills**: [`backend-patterns`]

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 3)
  - **Blocks**: Tasks 4, 5
  - **Blocked By**: None

  **References**:

  **Pattern References**:
  - `src/lifeops/core/config.py:32-45` — `LLMConfig` 作为模板
  - `src/lifeops/core/config.py:63-76` — `AppConfig` 集成方式

  **External References**:
  - serpapi Python 包: https://pypi.org/project/serpapi/ — 确认包名和版本

  **WHY Each Reference Matters**:
  - `LLMConfig` 是最直接的配置模板
  - `AppConfig` 展示子配置集成方式

  **Acceptance Criteria**:

  **QA Scenarios**:

  ```
  Scenario: SerpApiConfig 从环境变量读取 API Key
    Tool: Bash
    Preconditions: .env 包含 SERPAPI_API_KEY
    Steps:
      1. uv run python -c "from lifeops.core.config import AppConfig; c = AppConfig(); print('key_set:', bool(c.serpapi.api_key))"
    Expected Result: 输出 "key_set: True"
    Failure Indicators: 输出为 False 或报错
    Evidence: .sisyphus/evidence/task-2-config-read.txt

  Scenario: API Key 缺失时优雅降级
    Tool: Bash
    Steps:
      1. SERPAPI_API_KEY="" uv run python -c "from lifeops.core.config import AppConfig; c = AppConfig(); print('empty:', c.serpapi.api_key == '')"
    Expected Result: 配置正常初始化，api_key 为空字符串
    Failure Indicators: 程序崩溃或异常
    Evidence: .sisyphus/evidence/task-2-config-empty.txt
  ```

  **Commit**: YES (与 Task 3 合并提交)
  - Message: `feat(config): add SerpApiConfig and serpapi dependency`
  - Files: `src/lifeops/core/config.py`, `pyproject.toml`, `.env`, `.env.example`
  - Pre-commit: `uv run pytest tests/ -v`

- [x] 3. 添加 pytest slow marker 配置

  **What to do**:
  - 在 `pyproject.toml` 的 `[tool.pytest.ini_options]` 中添加 `markers = ["slow: marks tests as slow (deselect with '-m not slow')"]`
  - 这样集成测试可以用 `@pytest.mark.slow` 标记

  **Must NOT do**:
  - 不修改现有的测试配置

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 2)
  - **Blocks**: Task 5
  - **Blocked By**: None

  **References**:
  - `pyproject.toml:33-38` — `[tool.pytest.ini_options]` 现有配置

  **Acceptance Criteria**:

  **QA Scenarios**:

  ```
  Scenario: pytest 认识 slow marker
    Tool: Bash
    Steps:
      1. uv run pytest tests/ -v --co -m slow 2>&1 | head -20
      2. 验证不报 "unknown marker" 警告
    Expected Result: 没有 unknown marker 警告
    Failure Indicators: 出现 "unknown marker 'slow'" 警告
    Evidence: .sisyphus/evidence/task-3-pytest-marker.txt
  ```

  **Commit**: NO (合入 Task 2)

- [x] 4. 实现 web_search SerpApi 搜索工具

  **What to do**:
  - 在 `src/lifeops/tools/builtin/web_search.py` 中:
    - 定义 `WebSearchParams(BaseModel)`:
      - `query: str = Field(description="搜索查询关键词")`
      - `num_results: int = Field(default=10, ge=1, le=100, description="返回结果数量")`
      - `location: str | None = Field(default=None, description="搜索地理位置，如'Shanghai,China'")`
      - `language: str = Field(default="zh-cn", description="搜索语言，默认中文")` — 注: 默认 zh-cn 是有意的，匹配项目的中文环境
    - 实现 `create_web_search_tool(registry, config=None)`:
      - `config` 参数为 `AppConfig | None = None`（可选，None 默认值，不破坏现有调用方）
      - 在函数内创建 `serpapi.Client(api_key=key)` 一次，闭包捕获复用
      - 如果 `config` 为 None 或 `config.serpapi.api_key` 为空，handler 返回友好错误
      - 闭包内 handler 使用 `asyncio.to_thread(client.search, params_dict)` 异步调用
      - 格式化搜索结果: 每个结果包含标题、链接、摘要
      - 完整的 SerpApi 异常处理层级:
        ```
        except serpapi.APIKeyNotProvided: → "SerpApi API key not configured"
        except serpapi.TimeoutError: → "Search request timed out"
        except serpapi.HTTPError as e: → f"Search failed: {e.error}"
        except serpapi.SerpApiError as e: → f"Search error: {e}"
        ```
  - 更新 `src/lifeops/tools/builtin/__init__.py`:
    - `register_all_builtin_tools(registry, config=None)` — config 参数可选
    - `create_web_search_tool(registry, config)` 传入 config
  - 更新 `src/lifeops/agent.py`:
    - `_register_default_tools()` 传入 `self.config`

  **Must NOT do**:
  - ❌ 不使用已弃用的 `google-search-results` 包
  - ❌ 不在代码中硬编码 API Key
  - ❌ 不在 handler 中同步阻塞（必须用 `asyncio.to_thread()`）
  - ❌ 不每次搜索创建新的 Client（闭包捕获复用）
  - ❌ 不让 config 参数强制必填（None 默认值保持向后兼容）
  - ❌ 不在无 API Key 时崩溃（返回友好错误）

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: 核心新功能实现，涉及异步调用、错误处理、闭包模式
  - **Skills**: [`backend-patterns`]
    - `backend-patterns`: 异步模式、闭包模式、错误处理层级
  - **Skills Evaluated but Omitted**:
    - `security-review`: API Key 管理已通过项目现有模式处理

  **Parallelization**:
  - **Can Run In Parallel**: NO (depends on Tasks 1 and 2)
  - **Parallel Group**: Wave 2
  - **Blocks**: Tasks 5, 6
  - **Blocked By**: Tasks 1, 2

  **References**:

  **Pattern References**:
  - `src/lifeops/tools/builtin/bash.py` — 工具注册模式
  - `src/lifeops/core/config.py` — Config 注入模式

  **API/Type References**:
  - `src/lifeops/tools/base.py` (Task 1 产出) — `ToolParams` 基类, `ToolDefinition.parameters_model`
  - serpapi 包 API: `serpapi.Client(api_key=key)`, `client.search({"engine": "google", "q": ...})`, `SerpResults` 返回类型
  - serpapi 异常层级: `APIKeyNotProvided`, `TimeoutError`, `HTTPError`, `HTTPConnectionError`, `SerpApiError`

  **External References**:
  - serpapi Python 包: https://pypi.org/project/serpapi/ — 最新 API 文档

  **WHY Each Reference Matters**:
  - bash.py 提供工具注册的标准模式
  - config.py 展示配置注入方式
  - serpapi 包 API 与旧 `google-search-results` 完全不同，必须使用新接口
  - 异常层级必须完整捕获，避免未处理异常导致 agent 崩溃

  **Acceptance Criteria**:

  **QA Scenarios**:

  ```
  Scenario: API Key 缺失时优雅降级
    Tool: Bash
    Preconditions: SERPAPI_API_KEY 为空
    Steps:
      1. SERPAPI_API_KEY="" uv run python -c "
         from lifeops.core.config import AppConfig
         from lifeops.tools import ToolRegistry
         from lifeops.tools.builtin import register_all_builtin_tools
         import asyncio
         c = AppConfig()
         r = ToolRegistry()
         register_all_builtin_tools(r, c)
         result = asyncio.run(r.execute('web_search', {'query': 'test'}))
         print(result)"
      2. 验证返回 success=False, error 包含 "not configured" 或 "not set"
    Expected Result: 不崩溃，返回友好错误信息
    Failure Indicators: 程序崩溃或返回原始异常
    Evidence: .sisyphus/evidence/task-4-api-key-missing.txt

  Scenario: register_all_builtin_tests 不传 config 仍能工作
    Tool: Bash
    Steps:
      1. uv run python -c "
         from lifeops.tools import ToolRegistry
         from lifeops.tools.builtin import register_all_builtin_tools
         r = ToolRegistry()
         register_all_builtin_tools(r)  # 不传 config
         schemas = r.get_openai_tool_schemas()
         names = [s['function']['name'] for s in schemas]
         print(names)"
      2. 验证所有 4 个工具名都被注册
    Expected Result: ['bash', 'file_read', 'file_edit', 'web_search'] 或类似
    Failure Indicators: 缺少工具或 TypeError
    Evidence: .sisyphus/evidence/task-4-no-config-registration.txt

  Scenario: 网络超时错误处理
    Tool: Bash (通过 pytest mock)
    Preconditions: Mock SerpApi 抛出 TimeoutError
    Steps:
      1. uv run pytest tests/test_web_search.py -v -k "test_web_search_timeout"
    Expected Result: 超时被捕获并返回友好错误
    Failure Indicators: 未捕获的异常
    Evidence: .sisyphus/evidence/task-4-timeout-error.txt
  ```

  **Commit**: YES
  - Message: `feat(tools): implement web_search with SerpApi integration`
  - Files: `src/lifeops/tools/builtin/web_search.py`, `src/lifeops/tools/builtin/__init__.py`, `src/lifeops/agent.py`
  - Pre-commit: `uv run pytest tests/ -v -m "not slow"`

- [x] 5. web_search 完整测试套件（mock + 集成）

  **What to do**:
  - 更新 `tests/test_builtin_tools.py`:
    - 将 `test_web_search_placeholder` 替换为真实测试
    - 更新 `registry` fixture 支持 `config` 参数（可选）
  - 创建 `tests/test_web_search.py`:
    - Mock 单元测试:
      1. `test_web_search_success` — mock SerpApi 返回正常结果，验证格式化输出
      2. `test_web_search_empty_results` — mock 返回空结果，验证友好提示
      3. `test_web_search_api_error` — mock HTTPError，验证错误处理
      4. `test_web_search_timeout` — mock TimeoutError，验证超时处理
      5. `test_web_search_api_key_not_provided` — mock APIKeyNotProvided
      6. `test_web_search_no_api_key` — config 中 api_key 为空，验证优雅降级
      7. `test_web_search_params_validation` — 验证参数模型（必填参数、类型、范围）
      8. `test_web_search_serpapi_error_catchall` — mock SerpApiError 基类
    - 集成测试（标记为 `@pytest.mark.slow`）:
      9. `test_web_search_integration` — 用真实 SerpApi 搜索，验证端到端流程
  - 更新 `conftest.py` 如需要

  **Must NOT do**:
  - 不在单元测试中调用真实 SerpApi（仅集成测试调真实 API）
  - 不在 CI 中运行 slow 测试（由 pytest marker 控制）
  - 不 mock 内部实现细节（应 mock serpapi.Client 接口）

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: 全面测试覆盖，需要仔细设计 mock 场景
  - **Skills**: [`backend-patterns`]

  **Parallelization**:
  - **Can Run In Parallel**: NO (depends on Tasks 1, 2, 3, 4)
  - **Parallel Group**: Wave 2
  - **Blocks**: Task 6
  - **Blocked By**: Tasks 1, 2, 3, 4

  **References**:

  **Pattern References**:
  - `tests/test_builtin_tools.py` — 现有工具测试模式
  - `tests/conftest.py` — 公共 fixture 定义
  - serpapi 包: `import serpapi; serpapi.Client` — mock 目标

  **Test References**:
  - `tests/test_builtin_tools.py:112-115` — `test_web_search_placeholder` 需要替换

  **WHY Each Reference Matters**:
  - 现有测试模式提供项目约定的测试风格
  - placeholder 测试需要被替换
  - serpapi.Client 是 mock 的主要目标

  **Acceptance Criteria**:

  **If TDD**:
  - [ ] `uv run pytest tests/test_web_search.py -v -m "not slow"` → 8 tests PASS
  - [ ] `uv run pytest tests/ -v -m "not slow"` → ALL PASS

  **QA Scenarios**:

  ```
  Scenario: 所有 mock 单元测试通过
    Tool: Bash
    Steps:
      1. uv run pytest tests/test_web_search.py -v -m "not slow"
    Expected Result: 8 passed, 0 failed
    Failure Indicators: 任何测试失败
    Evidence: .sisyphus/evidence/task-5-mock-tests.txt

  Scenario: 集成测试被 slow marker 正确排除
    Tool: Bash
    Steps:
      1. uv run pytest tests/test_web_search.py -v -m "not slow" — 默认运行跳过 slow 测试
      2. uv run pytest tests/test_web_search.py -v -m slow --co — slow 测试被收集
    Expected Result: 默认运行不含 slow 测试，-m slow 可单独运行
    Failure Indicators: slow 测试在默认运行中执行
    Evidence: .sisyphus/evidence/task-5-slow-marker.txt
  ```

  **Commit**: YES
  - Message: `test(tools): add comprehensive web_search tests with mock and integration`
  - Files: `tests/test_web_search.py`, `tests/test_builtin_tools.py`, `tests/conftest.py`
  - Pre-commit: `uv run pytest tests/ -v -m "not slow"`

- [x] 6. 端到端集成验证

  **What to do**:
  - 运行完整测试套件: `uv run pytest tests/ -v -m "not slow"`
  - 运行 lint: `uv run ruff check src/ tests/`
  - 验证 web_search schema 输出:
    ```bash
    uv run python -c "from lifeops.tools import ToolRegistry; from lifeops.tools.builtin import register_all_builtin_tools; from lifeops.core.config import AppConfig; r = ToolRegistry(); c = AppConfig(); register_all_builtin_tools(r, c); schemas = r.get_openai_tool_schemas(); ws = [s for s in schemas if s['function']['name'] == 'web_search'][0]; print(ws)"
    ```
  - 验证配置读取: `uv run python -c "from lifeops.core.config import AppConfig; c = AppConfig(); print('serpapi_key_set:', bool(c.serpapi.api_key))"`
  - 验证 4 个工具的 schema 格式都正确

  **Must NOT do**:
  - 不修改代码（纯验证任务）
  - 不运行 slow 集成测试（除非用户明确要求）

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 3 (after Wave 2)
  - **Blocks**: F1-F4
  - **Blocked By**: Tasks 4, 5

  **References**:
  - 无新引用（使用之前所有 task 的产出）

  **Acceptance Criteria**:

  **QA Scenarios**:

  ```
  Scenario: 所有测试和 lint 通过
    Tool: Bash
    Steps:
      1. uv run pytest tests/ -v -m "not slow"
      2. uv run ruff check src/ tests/
    Expected Result: 所有测试 PASS，无 lint 错误
    Failure Indicators: 任何测试失败或 lint 警告
    Evidence: .sisyphus/evidence/task-6-test-lint.txt

  Scenario: web_search schema 输出标准 Function Calling 格式
    Tool: Bash
    Steps:
      1. 运行验证命令获取 web_search 的 tool schema
      2. 验证 schema 包含 "type": "function"、"function" 对象、"parameters" 包含 "query" 必填参数
    Expected Result: Schema 格式正确，符合 OpenAI Function Calling 规范
    Failure Indicators: 格式不完整或参数缺失
    Evidence: .sisyphus/evidence/task-6-schema-format.txt

  Scenario: 所有 4 个工具都能生成正确的 tool schema
    Tool: Bash
    Steps:
      1. 运行验证命令获取所有工具 schema
      2. 验证 4 个工具名称: bash, file_read, file_edit, web_search
      3. 验证每个 schema 包含正确的 properties 和 required 字段
    Expected Result: 4 个工具都被正确注册，schema 格式完整
    Failure Indicators: 工具缺失或 schema 格式错误
    Evidence: .sisyphus/evidence/task-6-all-schemas.txt
  ```

  **Commit**: YES
  - Message: `chore: update PROJECT.md with web_search and tool schema changes`
  - Files: `PROJECT.md`
  - Pre-commit: 无（文档更新）

---

## Final Verification Wave (mandatory — all implementation tasks 完成后)

> 4 个审查代理并行运行。全部必须 APPROVE。汇总结果后获得用户明确 "okay" 才能标记完成。
> **不要在获得用户 okay 之前将 F1-F4 标记为完成。**

- [ ] F1. **计划合规审计** — `oracle`
  端到端阅读计划。对每个 "Must Have": 验证实现存在（读文件、运行命令）。对每个 "Must NOT Have": 搜索代码库中禁止的模式。检查 `.sisyphus/evidence/` 中的证据文件。对比交付物与计划。
  重点检查:
  - `ToolParameter` 是否完全移除（grep 验证）
  - `.env` 文件中没有真实 API Key 泄露到 git
  - `serpapi` 包（而非 `google-search-results`）是否正确使用
  - `register_all_builtin_tools` 签名是否为可选 config 参数
  输出: `Must Have [N/N] | Must NOT Have [N/N] | Tasks [N/N] | VERDICT: APPROVE/REJECT`

- [ ] F2. **代码质量审查** — `unspecified-high`
  运行 `uv run ruff check src/ tests/` + `uv run pytest tests/ -v -m "not slow"`。审查所有变更文件：`as any`、空 catch、console.log in prod、注释掉的代码、未使用的导入。检查 AI slop：过多注释、过度抽象、泛型命名。
  输出: `Build [PASS/FAIL] | Lint [PASS/FAIL] | Tests [N pass/N fail] | Files [N clean/N issues] | VERDICT`

- [ ] F3. **手动 QA** — `unspecified-high`
  从干净状态开始。执行每个 QA 场景 — 遵循精确步骤，捕获证据。保存到 `.sisyphus/evidence/final-qa/`。
  输出: `Scenarios [N/N pass] | Integration [N/N] | VERDICT`

- [ ] F4. **范围保真检查** — `deep`
  对每个 task：读 "What to do"，读实际 diff。验证 1:1 — 规格中的都实现了（无遗漏），没做规格外的（无蔓延）。检查 "Must NOT do" 合规性。检测跨任务污染。
  重点检查:
  - Task 1 和工具迁移是否原子提交
  - API Key 是否只在 .env 中（不在源码或计划文件）
  - config 参数是否为可选（None 默认值）
  输出: `Tasks [N/N compliant] | Contamination [CLEAN/N issues] | VERDICT`

---

## Commit Strategy

- **1**: `refactor(tools): replace ToolParameter with Pydantic BaseModel schema system, migrate all tools`
  — `src/lifeops/tools/base.py`, `src/lifeops/tools/registry.py`, `src/lifeops/tools/builtin/bash.py`, `file_read.py`, `file_edit.py`, `tests/test_tool_registry.py`, `tests/test_builtin_tools.py`
  — 预提交: `uv run pytest tests/test_tool_registry.py tests/test_builtin_tools.py -v`

- **2+3**: `feat(config): add SerpApiConfig and serpapi dependency`
  — `src/lifeops/core/config.py`, `pyproject.toml`, `.env`, `.env.example`
  — 预提交: `uv run pytest tests/ -v`

- **4**: `feat(tools): implement web_search with SerpApi integration`
  — `src/lifeops/tools/builtin/web_search.py`, `src/lifeops/tools/builtin/__init__.py`, `src/lifeops/agent.py`
  — 预提交: `uv run pytest tests/ -v -m "not slow"`

- **5**: `test(tools): add comprehensive web_search tests with mock and integration`
  — `tests/test_web_search.py`, `tests/test_builtin_tools.py`, `tests/conftest.py`
  — 预提交: `uv run pytest tests/ -v -m "not slow"`

- **6**: `chore: update PROJECT.md with web_search and tool schema changes`
  — `PROJECT.md`
  — 预提交: 无（文档更新）

---

## Success Criteria

### 验证命令
```bash
uv run pytest tests/ -v -m "not slow"   # 所有测试通过（排除 slow 集成测试）
uv run ruff check src/ tests/             # 无 lint 错误
uv run python -c "from lifeops.tools import ToolRegistry; from lifeops.tools.builtin import register_all_builtin_tools; from lifeops.core.config import AppConfig; r = ToolRegistry(); c = AppConfig(); register_all_builtin_tools(r, c); schemas = r.get_openai_tool_schemas(); ws = [s for s in schemas if s['function']['name'] == 'web_search'][0]; print(ws)"  # 验证 web_search schema
uv run python -c "from lifeops.core.config import AppConfig; c = AppConfig(); print('serpapi_key_set:', bool(c.serpapi.api_key))"  # 验证配置可读取
```

### 最终检查清单
- [ ] 所有 "Must Have" 存在
- [ ] 所有 "Must NOT Have" 不存在
- [ ] 所有测试通过
- [ ] web_search 能返回格式化搜索结果
- [ ] API Key 缺失时返回友好错误
- [ ] ToolParameter 完全移除（grep 无结果）
- [ ] register_all_builtin_tools 的 config 参数为可选