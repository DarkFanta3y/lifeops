"""上下文洞察的 HTTP 接口。"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, FastAPI, HTTPException, Query

from lifeops.context_insight.queries import ContextInsightQueries


def register_context_routes(app: FastAPI) -> None:
    router = APIRouter()

    def queries() -> ContextInsightQueries:
        config = app.state.config.context
        prices = {
            "input": config.price_input_per_m,
            "output": config.price_output_per_m,
            "cache": config.price_cache_per_m,
        }
        return ContextInsightQueries(app.state.history_store, prices)

    @router.get("/api/conversations/{conversation_id}/context")
    async def conversation_context(conversation_id: str) -> dict[str, Any]:
        return queries().head(conversation_id)

    @router.get("/api/conversations/{conversation_id}/context/files")
    async def conversation_context_files(conversation_id: str) -> dict[str, Any]:
        return queries().files(conversation_id)

    @router.get("/api/conversations/{conversation_id}/context/fleet")
    async def conversation_context_fleet(conversation_id: str) -> dict[str, Any]:
        return queries().fleet(conversation_id)

    @router.get("/api/context/snapshots/{snapshot_id}")
    async def context_snapshot(snapshot_id: int) -> dict[str, Any]:
        detail = queries().snapshot_detail(snapshot_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="上下文快照不存在")
        return detail

    @router.get("/api/context/overview")
    async def context_overview(
        range_key: Literal["7d", "30d", "all"] = Query("7d", alias="range"),
    ) -> dict[str, Any]:
        return queries().overview(range_key)

    app.include_router(router)
