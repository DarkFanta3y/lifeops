# Learnings

## 2026-04-15 Session Start
- Project uses uv for dependency management
- serpapi package (NOT google-search-results) is the correct modern package
- serpapi.Client(api_key=key) creates a new requests.Session per instance - use closure pattern to reuse
- serpapi exceptions: APIKeyNotProvided, TimeoutError, HTTPError, HTTPConnectionError, SerpApiError (base)
- register_all_builtin_tools(registry, config=None) - config must be optional for backward compat
- ToolParameter removal + tool migration MUST be atomic (same commit)
- .sisyphus/ should be in .gitignore (needs manual addition)
## 2026-04-15 Task 2: SerpApiConfig + serpapi dependency
- serpapi 1.0.2 installed successfully via `uv sync`
- SerpApiConfig follows exact same pattern as LLMConfig: BaseSettings, env_prefix, env_file, extra="ignore"
- `AppConfig.serpapi = Field(default_factory=SerpApiConfig)` — nested config auto-reads from .env via env_prefix
- Env var naming: prefix `SERPAPI_` + field `api_key` = `SERPAPI_API_KEY` (pydantic-settings convention)
- Pre-existing test failures (3 import errors for `ToolParameter`) are from Task 1 — not caused by this task's changes
- Verified: `AppConfig().serpapi.api_key` reads from `.env` correctly; empty string fallback works

## 2026-04-15 Task 1: Pydantic 参数系统迁移

- `ToolParameter` dataclass 完全移除，替换为 `ToolParams(BaseModel)` 基类
- `ToolDefinition.parameters` (list[ToolParameter]) → `ToolDefinition.parameters_model` (type[ToolParams])
- 每个 builtin 工具定义了自己的 Params 类：BashParams, FileReadParams, FileEditParams, WebSearchParams
- `ToolParams` 使用 `model_config = {"extra": "forbid"}` 防止额外参数
- `_validate_params()` 从遍历 parameter list 改为 `definition.parameters_model.model_validate(params)`
- `get_openai_tool_schemas()` 从手动构建 schema 改为 `parameters_model.model_json_schema()`
- `llm/client.py` 的 `_build_tool_schemas()` 也需要同样修改（容易遗漏）
- 缺少必需参数时，Pydantic 抛出 `ValidationError`（是 `ValueError` 子类），测试用 `pytest.raises(ValidationError)` 更精确
- `model_json_schema()` 输出已包含 `properties` 和 `required`，但需要手动包装为 OpenAI function calling 格式
- web_search.py 虽然是 Task 4 的范围，但因 ToolParameter 移除必须同步迁移参数定义（不加 config）
- file_read 保留了 offset/limit 参数，同时添加了 encoding 参数
- file_edit 的 operation 字段使用 `Literal["create", "replace", "append"]`

## 2026-04-15 Task 4: Web Search SerpApi Implementation

- web_search.py uses closure pattern: `serpapi.Client(api_key=key)` created once in `create_web_search_tool`, captured in handler closure — NO new Client per search
- `asyncio.to_thread(client.search, params_dict)` wraps synchronous SerpApi calls for async compatibility
- Exception hierarchy handled in order: `serpapi.APIKeyNotProvided` → `serpapi.TimeoutError` → `serpapi.HTTPError` → `serpapi.SerpApiError`
- Graceful degradation: when config is None or api_key is empty string, tool still registers but handler returns `ToolResult(success=False, error="SerpApi API key 未配置...")`
- `register_all_builtin_tools(registry, config=None)` — config param is optional for backward compat
- `AppConfig(serpapi=SerpApiConfig(api_key=""))` is needed in tests to override .env values — `AppConfig()` reads from .env
- Test mock strategy: `patch("lifeops.tools.builtin.web_search.serpapi.Client")` must be applied BEFORE `register_all_builtin_tools` because Client is created at registration time (closure pattern)
- Helper `_make_registry_with_mocked_client()` encapsulates the patch-before-register pattern for test clarity
- `serpapi.HTTPError` inherits from both `requests.exceptions.HTTPError` and `SerpApiError` — requires a proper `requests.Response` mock to construct in tests
- `WebSearchParams` uses `model_config = {"extra": "forbid"}` inherited from `ToolParams`
- Chinese user-facing messages: error messages and result formatting in Chinese per project convention
- Search params: `q` (query), `num`, `hl` (language), `location` — mapped from WebSearchParams fields
- SerpResults is dict-like: `results.get("organic_results", [])` for result extraction
