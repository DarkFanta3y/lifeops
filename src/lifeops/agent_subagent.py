from __future__ import annotations

import json
from time import perf_counter
from typing import Any

from lifeops.llm.types import ChatResponse, Message, MessageRole, ToolCallResult
from lifeops.runtime.types import TraceEventType, TraceRecorder
from lifeops.tools.base import ToolResult
from lifeops.tools.registry import ToolRegistry
from lifeops.utils.logging import get_logger

logger = get_logger(__name__)

DEFAULT_SUBAGENT_TOOLS = ("file_read", "grep", "glob", "web_search", "retrieve_knowledge")

MAX_SUBAGENT_OUTPUT_CHARS = 8000

SUBAGENT_SYSTEM_PROMPT = """# 身份

你是 LifeOps 的子智能体，负责独立完成主智能体委派的探索型任务。

# 工作方式

- 只使用提供的只读工具收集信息；不修改任何文件或外部状态。
- 逐步推进：调用工具、观察结果、继续，直到能回答任务描述。
- 最终以简洁中文返回结论：直接给出答案、关键事实和必要的文件/行号引用；不要复述探索过程。
- 信息不足时明确说明缺少什么，不要臆造。"""


class SubAgentRunner:
    """精简 ReAct 循环：独立上下文 + 只读工具子集，仅返回最终结论文本。

    与主 Agent 的差异：不写历史/记忆、不经过工具策略（工具集已限定只读）、
    非流式调用 LLM、无 finish_task 协议（纯文本即结束）。
    """

    def __init__(
        self,
        *,
        llm: Any,
        source_registry: ToolRegistry,
        allowed_tools: list[str] | None = None,
        max_iterations: int = 10,
        run_id: str | None = None,
        trace_recorder: TraceRecorder | None = None,
    ) -> None:
        self.llm = llm
        self.max_iterations = max_iterations
        self.run_id = run_id
        self.trace_recorder = trace_recorder
        self.tools = self._build_subset_registry(
            source_registry, allowed_tools or list(DEFAULT_SUBAGENT_TOOLS)
        )

    def _build_subset_registry(
        self, source: ToolRegistry, allowed: list[str]
    ) -> ToolRegistry:
        registry = ToolRegistry()
        for name in allowed:
            definition = source.get_definition(name)
            handler = source.get_handler(name)
            if definition is None or handler is None:
                logger.warning(f"子智能体工具不可用，已跳过: {name}")
                continue
            registry.register(definition, handler)
        return registry

    def _record_trace(self, event_type: TraceEventType, payload: dict[str, Any]) -> None:
        if self.trace_recorder is None or not self.run_id:
            return
        try:
            self.trace_recorder.record(event_type, payload, run_id=self.run_id)
        except Exception:
            logger.exception("记录子智能体 trace 失败")

    async def run(self, prompt: str, *, description: str | None = None) -> str:
        started_at = perf_counter()
        self._record_trace(
            TraceEventType.SUBAGENT_STARTED,
            {
                "description": description,
                "prompt_length": len(prompt),
                "tools": sorted(
                    definition.name for definition in self.tools.list_definitions()
                ),
            },
        )
        messages: list[Message] = [
            Message(role=MessageRole.SYSTEM, content=SUBAGENT_SYSTEM_PROMPT),
            Message(role=MessageRole.USER, content=prompt),
        ]
        final_text = ""
        try:
            for _ in range(self.max_iterations):
                response: ChatResponse = await self.llm.chat(
                    messages, tools=self.tools.list_definitions()
                )
                if not response.tool_calls:
                    final_text = response.content or ""
                    break
                messages.append(
                    Message(
                        role=MessageRole.ASSISTANT,
                        content=response.content,
                        tool_calls=[
                            {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                            for tc in response.tool_calls
                        ],
                        reasoning_content=response.reasoning_content,
                    )
                )
                for tc in response.tool_calls:
                    result = await self._execute(tc)
                    messages.append(
                        Message(
                            role=MessageRole.TOOL,
                            content=(result.output if result.success else f"Error: {result.error}"),
                            tool_call_id=tc.id,
                            name=tc.name,
                        )
                    )
            else:
                final_text = final_text or "子智能体已达到迭代上限，未能得出完整结论。"
        except Exception as error:
            logger.exception("子智能体运行失败")
            final_text = f"子智能体运行失败: {error}"

        self._record_trace(
            TraceEventType.SUBAGENT_FINISHED,
            {
                "description": description,
                "duration_ms": round((perf_counter() - started_at) * 1000, 2),
                "output_length": len(final_text),
            },
        )
        if len(final_text) > MAX_SUBAGENT_OUTPUT_CHARS:
            final_text = (
                final_text[:MAX_SUBAGENT_OUTPUT_CHARS]
                + "\n...[子智能体输出超长，已截断]"
            )
        return final_text

    async def _execute(self, tc: ToolCallResult) -> ToolResult:
        try:
            params = json.loads(tc.arguments)
        except (json.JSONDecodeError, TypeError):
            return ToolResult(success=False, output="", error="工具参数 JSON 无效")
        if not isinstance(params, dict):
            return ToolResult(success=False, output="", error="工具参数必须是 JSON 对象")
        try:
            return await self.tools.execute(tc.name, params)
        except KeyError:
            return ToolResult(success=False, output="", error=f"Unknown tool: {tc.name}")
        except Exception as error:
            return ToolResult(success=False, output="", error=str(error))
