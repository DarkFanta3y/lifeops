from __future__ import annotations

import json
from time import perf_counter
from typing import Any
from uuid import uuid4

from lifeops.context_insight import ContextSnapshotStore, SystemPart, build_composition
from lifeops.llm.types import ChatResponse, Message, MessageRole, ToolCallResult
from lifeops.runtime.types import TraceEventType, TraceRecorder
from lifeops.tools.base import ToolResult
from lifeops.tools.registry import ToolRegistry
from lifeops.utils.logging import get_logger

logger = get_logger(__name__)

DEFAULT_SUBAGENT_TOOLS = ("file_read", "grep", "glob", "web_search", "retrieve_knowledge")

MAX_SUBAGENT_OUTPUT_CHARS = 8000

TRACE_EXCERPT_CHARS = 2000

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
        context_recorder: ContextSnapshotStore | None = None,
        conversation_id: str | None = None,
    ) -> None:
        self.llm = llm
        self.max_iterations = max_iterations
        self.run_id = run_id
        self.trace_recorder = trace_recorder
        self.context_recorder = context_recorder
        self.conversation_id = conversation_id
        self.agent_id = f"sub_{uuid4().hex[:8]}"
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
                "agent_id": self.agent_id,
                "description": description,
                "prompt": prompt[:TRACE_EXCERPT_CHARS],
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
            for iteration in range(self.max_iterations):
                tools = self.tools.list_definitions()
                snapshot_id = self._capture_snapshot(messages, tools, iteration)
                call_started_at = perf_counter()
                response: ChatResponse = await self.llm.chat(messages, tools=tools)
                if snapshot_id is not None and self.context_recorder is not None:
                    self.context_recorder.finish(
                        snapshot_id,
                        usage=response.usage,
                        duration_ms=(perf_counter() - call_started_at) * 1000,
                        text=response.content,
                        calls=[tc.name for tc in response.tool_calls or []],
                    )
                if not response.tool_calls:
                    final_text = response.content or ""
                    break
                messages.append(
                    Message(
                        role=MessageRole.ASSISTANT,
                        content=response.content,
                        tool_calls=[
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {"name": tc.name, "arguments": tc.arguments},
                            }
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
                "agent_id": self.agent_id,
                "description": description,
                "output": final_text[:TRACE_EXCERPT_CHARS],
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

    def _capture_snapshot(self, messages: list[Message], tools: list[Any], iteration: int) -> int | None:
        if self.context_recorder is None or not self.run_id or not self.conversation_id:
            return None

        def estimate(text: str) -> int:
            return max(1, len(text) // 4)

        def estimate_message(message: Message) -> int:
            return estimate(json.dumps(message.to_dict(), ensure_ascii=False, separators=(",", ":")))

        try:
            elements = build_composition(
                system_parts=[SystemPart("system", "子智能体系统提示", messages[0].content or "")],
                messages=messages[1:],
                tools=tools,
                estimate=estimate,
                estimate_message=estimate_message,
            )
        except Exception:
            logger.exception("构建子智能体上下文构成失败")
            return None
        return self.context_recorder.capture(
            run_id=self.run_id,
            conversation_id=self.conversation_id,
            elements=elements,
            agent_id=self.agent_id,
            parent_agent_id="main",
            iteration=iteration,
            model=getattr(self.llm, "model", None),
        )

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
