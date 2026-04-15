# Decisions

## 2026-04-15
- Use `serpapi` package (NOT deprecated `google-search-results`)
- Pydantic BaseModel for tool parameters (NOT enhanced dataclass)
- SerpApiConfig with env prefix `SERPAPI_`, field `api_key`
- Environment variable: `SERPAPI_API_KEY`
- register_all_builtin_tools config param: optional (None default)
- web_search handler: closure pattern with Client reuse
- Exception hierarchy: APIKeyNotProvided → TimeoutError → HTTPError → SerpApiError
- language default: "zh-cn" (matches project Chinese orientation)
- Task 1+4 merged into atomic commit (can't remove ToolParameter while tools still import it)