from __future__ import annotations

import asyncio
from typing import Any

import serpapi
from pydantic import Field

from lifeops.core.config import AppConfig
from lifeops.tools.base import ToolDefinition, ToolParams, ToolResult
from lifeops.tools.registry import ToolRegistry
from lifeops.utils.logging import get_logger

logger = get_logger(__name__)


class WebSearchParams(ToolParams):
    query: str
    num_results: int = Field(default=10, ge=1, le=100)
    location: str | None = None
    language: str = Field(default="zh-cn")


def create_web_search_tool(registry: ToolRegistry, config: AppConfig | None = None) -> None:
    api_key = config.serpapi.api_key if config else ""

    definition = ToolDefinition(
        name="web_search",
        description="搜索互联网获取信息，返回相关网页标题、链接和摘要",
        parameters_model=WebSearchParams,
        category="builtin",
    )

    if not api_key:

        async def _handler(params: dict[str, Any]) -> ToolResult:
            return ToolResult(
                success=False,
                output="",
                error="SerpApi API key 未配置。请设置 SERPAPI_API_KEY 环境变量。",
            )
    else:
        client = serpapi.Client(api_key=api_key)

        async def _handler(params: dict[str, Any]) -> ToolResult:
            validated = WebSearchParams.model_validate(params)
            logger.info(f"Web search: {validated.query}")

            search_params: dict[str, Any] = {
                "q": validated.query,
                "num": validated.num_results,
                "hl": validated.language,
            }
            if validated.location:
                search_params["location"] = validated.location

            try:
                results = await asyncio.to_thread(client.search, search_params)
            except serpapi.APIKeyNotProvided:
                return ToolResult(
                    success=False,
                    output="",
                    error="SerpApi API key 未配置。请设置 SERPAPI_API_KEY 环境变量。",
                )
            except serpapi.TimeoutError:
                return ToolResult(
                    success=False,
                    output="",
                    error="搜索请求超时，请稍后重试。",
                )
            except serpapi.HTTPError as e:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"搜索失败: {e.error}",
                )
            except serpapi.SerpApiError as e:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"搜索错误: {e}",
                )

            organic = results.get("organic_results", [])
            if not organic:
                return ToolResult(
                    success=True,
                    output=f"未找到与「{validated.query}」相关的搜索结果。",
                )

            lines = [f"搜索结果 (共 {len(organic)} 条):\n"]
            for i, item in enumerate(organic, 1):
                title = item.get("title", "无标题")
                link = item.get("link", "")
                snippet = item.get("snippet", "")
                lines.append(f"{i}. [{title}]({link})")
                if snippet:
                    lines.append(f"   {snippet}")
                lines.append("")

            return ToolResult(success=True, output="\n".join(lines))

    registry.register(definition, _handler)
