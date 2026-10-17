"""对话展示活动：记录调用身份与快照，不把展示字段注入模型上下文。"""
from __future__ import annotations

import asyncio
from contextvars import ContextVar
from time import time
from typing import Any
from uuid import uuid4

from lifeops.utils.logging import get_logger

logger = get_logger(__name__)
active_call: ContextVar[str | None] = ContextVar("lifeops_active_tool_call", default=None)


class ToolActivity:
    def __init__(self, agent: Any):
        self.agent = agent
        self.calls: dict[str, dict[str, Any]] = {}
        self.iteration = 0
        self.run_id = ""
        self.user_message_id: int | None = None
        self.prepares: dict[int, str] = {}
        self.status = "running"
        self.error: str | None = None
        self.pending_text = ""
        self.final_output: str | None = None

    def reset(self) -> None:
        self.__init__(self.agent)
        self.run_id = self.agent.run_id or uuid4().hex

    async def emit(self, kind: str, data: dict[str, Any]) -> None:
        callback = getattr(self.agent, "on_activity", None)
        if callback is not None:
            await callback(kind, {"run_id": self.run_id, "iteration": self.iteration, **data})

    async def prepare(self, name: str, params: dict | None, index: int) -> None:
        if not name or name == "finish_task":
            return
        key = f"{self.run_id}:{self.iteration}:{index}"
        self.prepares[index] = key
        await self.emit("tool_prepare", {
            "prepare_key": key, "tool_name": name, "args": params,
            "has_args": params is not None,
            "canonical_name": self.agent.tools.get_canonical_name(name), "status": "preparing",
        })

    def save(self, snapshot: dict[str, Any]) -> None:
        save = getattr(self.agent.history_store, "append_tool_execution", None)
        if save is not None:
            try:
                save(snapshot["call_id"], snapshot)
            except Exception:
                logger.exception("保存工具展示快照失败")

    async def requested(self, tc: Any, params: dict) -> None:
        snapshot = {
            "call_id": tc.id, "run_id": self.run_id, "iteration": self.iteration,
            "user_message_id": self.user_message_id,
            "tool_name": tc.name, "canonical_name": self.agent.tools.get_canonical_name(tc.name),
            "args": params, "status": "queued", "requested_at_ms": int(time() * 1000),
            "prepare_key": self.prepares.get(getattr(self.agent, "_tool_index", 0)),
        }
        self.calls[tc.id] = snapshot
        self.save(snapshot)
        await self.emit("tool_call", snapshot)

    async def update(self, call_id: str | None, **fields: Any) -> None:
        if call_id not in self.calls:
            return
        snapshot = {**self.calls[call_id], **fields}
        self.calls[call_id] = snapshot
        self.save(snapshot)
        await self.emit("tool_status", {
            "call_id": call_id, "tool_name": snapshot["tool_name"],
            "iteration": snapshot.get("iteration", self.iteration), **fields,
        })

    async def result(self, tc: Any, result: Any, duration_ms: float) -> None:
        snapshot = {
            **self.calls.get(tc.id, {}), "call_id": tc.id, "tool_name": tc.name,
            "status": "completed" if result.success else "failed",
            "success": result.success, "output": result.output, "error": result.error,
            "metadata": result.metadata, "duration_ms": round(duration_ms, 2),
            "ended_at_ms": int(time() * 1000),
        }
        self.calls[tc.id] = snapshot
        self.save(snapshot)
        await self.emit("tool_result", snapshot)

    async def finish(self, status: str, error: str | None = None) -> None:
        self.status = status
        self.error = error
        for call_id, snapshot in list(self.calls.items()):
            fields: dict[str, Any] = {"turn_status": status, "turn_error": error}
            if snapshot["status"] in {"queued", "running", "waiting_approval"}:
                fields.update(status="interrupted", ended_at_ms=int(time() * 1000))
            await self.update(call_id, **fields)
        await self.emit("run_finished", {
            "status": status, "error": error, "final_output": self.final_output,
        })

    async def execute(self, tc: Any, params: dict, policy_result: Any) -> Any:
        """审批等待、实际执行和取消都保留精确调用身份。"""
        token = active_call.set(tc.id)
        try:
            result = self.agent._plan_gate_result(tc)
            if result is None:
                result = await self.agent._resolve_policy_denial(tc, policy_result)
            if result is None:
                await self.update(tc.id, status="running", started_at_ms=int(time() * 1000))
                result = await self.agent._execute_tool_handler(tc, params)
            return result
        except asyncio.CancelledError:
            await self.update(tc.id, status="interrupted", ended_at_ms=int(time() * 1000))
            raise
        finally:
            active_call.reset(token)
