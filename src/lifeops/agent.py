from __future__ import annotations

import json
import os
import inspect
from dataclasses import dataclass
from datetime import datetime
from time import perf_counter
from typing import Any, Literal
from uuid import uuid4

from pydantic import Field, model_validator

from lifeops.core.compression_pipeline import CompressionPipeline
from lifeops.core.config import AppConfig
from lifeops.core.context_manager import ContextLayer, ContextManager
from lifeops.history import ConversationHistoryStore, HistorySource
from lifeops.llm.client import LLMClient
from lifeops.llm.types import ChatResponse, LLMError, Message, MessageRole, ToolCallResult
from lifeops.runtime.errors import AgentRuntimeError, RuntimeErrorType
from lifeops.runtime.policy import ToolPolicyContext, ToolPolicyEngine
from lifeops.runtime.policy_rules import PolicyAction
from lifeops.runtime.types import RunStatus, TraceEventType, TraceRecorder
from lifeops.skills.manager import SkillManager
from lifeops.skills.matcher import SkillMatcher
from lifeops.skills.types import SkillCatalog
from lifeops.tools.base import ToolDefinition, ToolParams, ToolResult
from lifeops.tools.builtin import register_all_builtin_tools
from lifeops.tools.mcp.manager import MCPManager
from lifeops.tools.mcp.types import MCPServerConfig
from lifeops.tools.registry import ToolRegistry
from lifeops.tools.schema import ToolSelectionContext, openai_tool_schema, select_llm_tools
from lifeops.utils.logging import get_logger
from lifeops.utils.text import sanitize_unicode_text

logger = get_logger(__name__)


class _FinishTaskParams(ToolParams):
    status: Literal["complete", "needs_user", "blocked"]
    answer: str = Field(min_length=1, description="面向用户的最终答复")
    missing_information: str | None = Field(
        default=None,
        description="需要用户补充的信息或当前阻塞原因",
    )

    @model_validator(mode="after")
    def validate_completion_status(self) -> "_FinishTaskParams":
        missing = (self.missing_information or "").strip()
        if self.status in {"needs_user", "blocked"} and not missing:
            raise ValueError("needs_user 或 blocked 必须说明缺失信息或阻塞原因")
        return self


@dataclass
class AgentServices:
    llm: LLMClient
    base_tool_registry: ToolRegistry
    mcp_manager: MCPManager
    rag_router: Any | None = None
    skill_catalog: SkillCatalog | None = None

DEFAULT_SYSTEM_PROMPT = """# 身份与目标

你是 LifeOps，一个面向个人生活管理的 AI 助理。帮助用户整理任务、日程、健康、财务、资料、长期目标和个人工作流，把模糊想法转化为可执行的下一步。

# 工作方式

- 简单问题直接回答；复杂任务先拆解关键步骤再推进。
- 信息不足且会影响结果时先澄清；可基于合理假设继续时，说明假设。
- 输出以行动为导向：结论、步骤、清单或可直接使用的文本。

# 上下文使用

- 不臆造上下文中没有的信息；不确定时说明不确定性，并给出可验证的下一步。
- 上下文冲突时遵循用户最新明确指令；必要时指出冲突并请用户确认。

# 工具使用策略

- 需要读取或编辑文件、执行命令、搜索互联网或调用 MCP 时，使用对应工具。
- 系统已提供检索结果时优先直接使用，不重复检索；仍缺信息或需操作时才继续调用工具。
- 工具失败或权限受限时，说明限制、已尝试内容和下一步选择。
- 不为可直接回答的常识性或低风险问题过度调用工具。

# Skill 协作

- 已激活 Skill 的正文优先于本提示词中的通用规则；与用户最新指令冲突时以用户指令为准。

# 任务闭环

- 工具执行后必须观察工具结果，再判断原始目标是否已经满足。
- 每轮最多执行一个工具；不要在没有观察当前结果前预先执行下一步。
- 如果目标已完成、需要用户补充信息或无法安全继续，调用 `finish_task` 明确结束。
- 已执行过工具后，不要直接输出普通文本作为最终回答；只能调用下一工具或 `finish_task`。
- 不要把工具调用成功误认为任务完成；工具结果只是观察信息。

# 安全与边界

- 不协助违法、危险、侵犯隐私、绕过安全控制、泄露凭证或滥用外部服务的请求。
- 健康、财务、法律等高风险事项只提供一般信息和决策框架，提示不确定性并建议核验。
- 处理个人数据、账号、文件和外部服务时，只执行用户授权范围内的操作。

# 语气与输出

- 始终优先使用中文，表达清晰、详尽。
- 需要计划时给计划；需要结果时给结论和行动项。
- 保持稳定可靠，不夸大能力，不承诺无法验证的结果。"""


class Agent:
    def __init__(
        self,
        config: AppConfig,
        system_prompt: str | None = None,
        history_store: ConversationHistoryStore | None = None,
        source: HistorySource = "web",
        conversation_id: str | None = None,
        services: AgentServices | None = None,
        memory_service: Any | None = None,
        run_id: str | None = None,
        trace_recorder: TraceRecorder | None = None,
        tool_policy_engine: ToolPolicyEngine | None = None,
    ):
        self.config = config
        self.services = services
        self.llm = services.llm if services is not None else LLMClient(
            api_key=config.llm.api_key,
            model=config.llm.model,
            api_base=config.llm.api_base,
            max_tokens=config.llm.max_tokens,
            temperature=config.llm.temperature,
            timeout=config.llm.timeout,
        )
        self.tools = services.base_tool_registry.clone() if services is not None else ToolRegistry()
        self.mcp_manager = services.mcp_manager if services is not None else MCPManager()
        self.context = ContextManager(
            max_tokens=config.context.max_context_tokens,
            l1_budget_ratio=config.context.l1_budget_ratio,
            l2_budget_ratio=config.context.l2_budget_ratio,
            l3_budget_ratio=config.context.l3_budget_ratio,
            reserve_ratio=config.context.reserve_ratio,
        )
        self.system_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT
        self.messages: list[Message] = []
        self.max_iterations = 10
        self.on_tool_prepare: Any | None = None
        self.on_tool_call: Any | None = None
        self.on_tool_result: Any | None = None
        self.on_token: Any | None = None
        self.skill_manager: SkillManager | None = None
        self.skill_matcher: SkillMatcher | None = None
        self.rag_router: Any | None = None
        self._mcp_tools_registered = services is not None
        self.history_store = history_store or ConversationHistoryStore(config.history_path)
        self.source = source
        self.conversation_id = conversation_id or self._new_conversation_id()
        self.memory_service = memory_service
        self.run_id = run_id
        self.trace_recorder = trace_recorder
        self.tool_policy_engine = tool_policy_engine or ToolPolicyEngine(config.tool_policy)

        if services is not None:
            self.rag_router = services.rag_router
        elif config.rag.enabled:
            from lifeops.rag.router import build_default_rag_router

            self.rag_router = build_default_rag_router(config.rag)

        if services is None:
            self._register_default_tools()
        self._register_finish_task_tool()
        self._register_rag_tool()

        # MCP 静态配置加载
        if (
            services is None
            and config.mcp.enabled
            and (config.mcp.servers.strip() or config.mcp.presets.strip())
        ):
            if config.mcp.servers.strip():
                self.mcp_manager.load_from_config(config.mcp.servers)
            if config.mcp.presets.strip() and not _should_skip_pytest_env_mcp(config.mcp.presets):
                self.mcp_manager.load_presets(config.mcp.presets)

        if config.skills.enabled:
            self.skill_manager = self._create_skill_manager()
            self.skill_matcher = SkillMatcher(self.llm)
            if services is not None and services.skill_catalog is not None:
                self.skill_manager.catalog = services.skill_catalog
                self.skill_manager.inject_catalog()
            else:
                self.skill_manager.discover()
            self._register_activate_skill_tool()

    def _create_skill_manager(self) -> SkillManager:
        return SkillManager(
            context=self.context,
            project_dir=self.config.skills.project_dir,
            user_dir=self.config.skills.user_dir,
            max_active=self.config.skills.max_active,
        )

    def _register_default_tools(self) -> None:
        register_all_builtin_tools(self.tools, self.config)

    def _register_finish_task_tool(self) -> None:
        async def handler(params: dict[str, Any]) -> ToolResult:
            validated = _FinishTaskParams.model_validate(params)
            return ToolResult(
                success=True,
                output=validated.answer,
                metadata={
                    "task_status": validated.status,
                    "missing_information": validated.missing_information,
                },
            )

        self.tools.register(
            ToolDefinition(
                name="finish_task",
                description=(
                    "任务完成判断工具。执行过其他工具后必须使用它结束本轮任务。"
                    "status=complete 表示目标已满足；needs_user 表示必须向用户补充信息；"
                    "blocked 表示没有安全可行的下一步。"
                ),
                parameters_model=_FinishTaskParams,
                category="internal",
                canonical_name="internal.finish_task",
                read_only=True,
                risk_level="low",
            ),
            handler,
        )

    def _register_rag_tool(self) -> None:
        if not self.config.rag.enabled or self.rag_router is None:
            return

        from pydantic import Field

        class RetrieveKnowledgeParams(ToolParams):
            query: str = Field(min_length=1, description="要在本地知识库中检索的问题")
            source: str = Field(
                min_length=1,
                description="要检索的数据源标识，必须使用工具描述中列出的值",
            )
            top_files: int = Field(default=3, ge=1, le=10, description="最多返回的文件数量")

        async def handler(params: dict[str, Any]) -> ToolResult:
            validated = RetrieveKnowledgeParams.model_validate(params)
            source = validated.source.strip()
            if not source:
                return ToolResult(success=False, output="", error="本地知识库不能为空")
            top_files = min(validated.top_files, 3)
            try:
                result = await self.rag_router.retrieve(
                    validated.query,
                    source=source,
                    top_files=top_files,
                )
            except ValueError as exc:
                return ToolResult(success=False, output="", error=str(exc))
            except Exception as exc:
                logger.exception("本地知识库检索失败")
                return ToolResult(
                    success=False,
                    output="",
                    error=f"本地知识库检索失败：{str(exc)[:120]}",
                    metadata={"error_type": RuntimeErrorType.RAG_ERROR.value},
                )
            return ToolResult(
                success=True,
                output=result.output,
                metadata={
                    "source": source,
                    "result_count": result.result_count,
                    "top_files": top_files,
                },
            )

        catalog = self.rag_router.format_source_catalog()
        self.tools.register(
            ToolDefinition(
                name="retrieve_knowledge",
                description=(
                    "本地知识库路由检索。仅在用户请求涉及下方本地数据源时调用；"
                    "调用时必须传入匹配的 source。不要用于实时网络信息、新闻、政策、价格、公开网页事实或最新版本信息。\n"
                    f"{catalog}"
                ),
                parameters_model=RetrieveKnowledgeParams,
                category="builtin",
                canonical_name="builtin.retrieve_knowledge",
                read_only=True,
                risk_level="low",
            ),
            handler,
        )

    def _register_activate_skill_tool(self) -> None:
        if self.skill_manager is None:
            return

        from pydantic import Field

        class ActivateSkillParams(ToolParams):
            name: str = Field(min_length=1, description="要激活的 Skill 名称")
            reason: str | None = Field(default=None, description="激活原因")

        async def handler(params: dict[str, Any]) -> ToolResult:
            validated = ActivateSkillParams.model_validate(params)
            return self._activate_skill_by_name(
                validated.name,
                activation_type="tool",
                reason=validated.reason,
            )

        self.tools.register(
            ToolDefinition(
                name="activate_skill",
                description=(
                    "内部 Skill 激活工具。何时调用：用户需要使用某个可用 Skill 的完整工作流，"
                    "或当前任务明显匹配 Skill 目录摘要。参数 name 必须来自可用 Skill 目录。"
                ),
                parameters_model=ActivateSkillParams,
                category="internal",
                canonical_name="internal.activate_skill",
                read_only=True,
                risk_level="low",
            ),
            handler,
        )

    async def _connect_mcp_servers(self) -> None:
        from lifeops.tools.mcp.adapter import MCPRegistryAdapter

        for server_name in self.mcp_manager.list_servers():
            try:
                await self.mcp_manager.connect_server(server_name)
                client = self.mcp_manager.get_client(server_name)
                if client is None:
                    continue

                tools = await client.list_tools()
                if tools:
                    adapter = MCPRegistryAdapter(self.tools, client)
                    adapter.register_tools(tools)
            except Exception:
                logger.exception(f"MCP server '{server_name}' 连接失败")

    async def _ensure_mcp_tools_registered(self) -> None:
        """在首次 LLM 调用前把已配置的 MCP 工具注册到工具表。"""
        if self._mcp_tools_registered:
            return
        if not self.mcp_manager.list_servers():
            self._mcp_tools_registered = True
            return

        await self.mcp_manager.connect_and_register_all(self.tools)
        self._mcp_tools_registered = True

    def add_tool(self, definition: ToolDefinition, handler: Any) -> None:
        self.tools.register(definition, handler)

    def add_mcp_server(self, name: str, config: MCPServerConfig) -> None:
        """动态注册 MCP server 配置。连接和工具注册在 Wave 2 Adapter 中完成。"""
        self.mcp_manager.add_server(name, config)
        self._mcp_tools_registered = False

    def remove_mcp_server(self, name: str) -> None:
        """动态移除 MCP server 配置。工具解绑在 Wave 2 Adapter 中完成。"""
        self.mcp_manager.remove_server(name)
        self._mcp_tools_registered = False

    def _build_messages(self, task_instruction: str | None = None) -> list[Message]:
        result = [
            Message(
                role=MessageRole.SYSTEM,
                content=self._build_system_context(task_instruction),
            )
        ]
        result.extend(self.messages)
        return result

    def _build_system_context(self, task_instruction: str | None = None) -> str:
        sections: list[str] = [f"## 当前信息\n当前日期：{datetime.now():%Y-%m-%d}"]
        for title, entries in (
            ("L1 常驻上下文", self.context.get_l1_content()),
            ("L2 按需上下文", self.context.get_l2_content()),
            ("L3 工具结果上下文", self.context.get_l3_content()),
        ):
            content_entries = [
                entry
                for entry in sorted(entries, key=lambda item: item.key)
                if not entry.key.startswith(("user_", "assistant_", "tool_"))
            ]
            if not content_entries:
                continue
            section = "\n\n".join(entry.content for entry in content_entries)
            sections.append(f"## {title}\n{section}")
        if task_instruction:
            sections.append(f"## 当前任务闭环\n{task_instruction}")
        return "\n\n".join([self.system_prompt, *sections])

    def _prepare_llm_messages(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None,
        *,
        run_message_start: int = 0,
    ) -> tuple[list[Message], dict[str, int]]:
        prepared = list(messages)
        budget = self.config.context.max_context_tokens
        tool_schema_tokens = self._estimate_tool_schema_tokens(tools)
        system_tokens = self._estimate_message_tokens(prepared[0]) if prepared else 0
        history_tokens = sum(self._estimate_message_tokens(message) for message in prepared[1:])
        trimmed_message_count = 0
        truncated_tool_output_count = 0

        def total_tokens() -> int:
            return (
                sum(self._estimate_message_tokens(message) for message in prepared)
                + tool_schema_tokens
            )

        historical_end = min(1 + run_message_start, len(prepared))
        while total_tokens() > budget and len(prepared) > 1 and historical_end > 1:
            prepared.pop(1)
            historical_end -= 1
            trimmed_message_count += 1

        current_run_tool_indexes = [
            index
            for index, message in enumerate(prepared[historical_end:], start=historical_end)
            if message.role == MessageRole.TOOL
        ]
        for index in current_run_tool_indexes:
            if total_tokens() <= budget:
                break
            message = prepared[index]
            if message.content is None:
                continue
            old_content = message.content
            excess = total_tokens() - budget
            new_length = max(0, len(old_content) - excess * 4)
            if new_length == len(old_content):
                new_length = max(0, len(old_content) - 1)
            prepared[index] = Message(
                role=message.role,
                content=old_content[:new_length],
                tool_calls=message.tool_calls,
                tool_call_id=message.tool_call_id,
                name=message.name,
                reasoning_content=message.reasoning_content,
            )
            truncated_tool_output_count += 1

        estimated_tokens = total_tokens()
        stats = {
            "system_tokens": system_tokens,
            "history_tokens": history_tokens,
            "tool_schema_tokens": tool_schema_tokens,
            "estimated_tokens": estimated_tokens,
            "context_budget": budget,
            "trimmed_message_count": trimmed_message_count,
            "truncated_tool_output_count": truncated_tool_output_count,
        }
        if estimated_tokens > budget:
            raise AgentRuntimeError(
                RuntimeErrorType.CONTEXT_ERROR,
                "context_error",
                details=stats,
            )
        return prepared, stats

    def _estimate_message_tokens(self, message: Message) -> int:
        return self.context.estimate_tokens(
            json.dumps(message.to_dict(), ensure_ascii=False, separators=(",", ":"))
        )

    def _estimate_tool_schema_tokens(self, tools: list[ToolDefinition] | None) -> int:
        if not tools:
            return 0
        return sum(
            self.context.estimate_tokens(
                json.dumps(openai_tool_schema(tool), ensure_ascii=False, separators=(",", ":"))
            )
            for tool in tools
        )

    def _record_llm_call_started(
        self, budget: dict[str, int], payload: dict[str, Any]
    ) -> None:
        self._record_trace(
            TraceEventType.LLM_CALL_STARTED,
            {
                **payload,
                **budget,
            },
        )

    async def _chat_stream_with_retry(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None,
        *,
        emit_content: bool = True,
    ) -> tuple[ChatResponse, bool]:
        for attempt in range(2):
            content_parts: list[str] = []
            reasoning_parts: list[str] = []
            stream_tool_calls: list[dict[str, Any]] = []
            stream = self.llm.chat_stream(messages, tools=tools)
            if not hasattr(stream, "__aiter__"):
                if inspect.iscoroutine(stream):
                    stream.close()
                try:
                    return await self.llm.chat(messages, tools=tools), False
                except LLMError as exc:
                    self._fail_run(exc.error_type, exc.message)
                    raise

            stream_error: dict[str, Any] | None = None
            async for event in stream:
                event_type = event.get("type") if isinstance(event, dict) else None
                data = event.get("data") if isinstance(event, dict) else None
                if event_type == "token" and isinstance(data, str) and data:
                    content_parts.append(data)
                    if emit_content:
                        await self.on_token(data)
                elif event_type == "tool_call_start" and isinstance(data, dict):
                    await self._prepare_tool_call(data.get("name", ""), None, status="started")
                elif event_type == "tool_call_ready" and isinstance(data, dict):
                    await self._prepare_tool_call(
                        data.get("name", ""),
                        data.get("args") if isinstance(data.get("args"), dict) else None,
                        status="ready",
                    )
                elif event_type == "tool_call" and isinstance(data, dict):
                    stream_tool_calls.append(data)
                elif event_type == "reasoning_content" and isinstance(data, str):
                    reasoning_parts.append(data)
                elif event_type == "error":
                    stream_error = self._stream_error_payload(data)
                    break

            emitted = bool(content_parts or reasoning_parts or stream_tool_calls)
            if stream_error is not None:
                retryable = self._stream_error_can_retry(stream_error, emitted, attempt)
                self._record_trace(
                    TraceEventType.LLM_ERROR,
                    {**stream_error, "attempt": attempt + 1, "retrying": retryable},
                )
                if retryable:
                    continue
                self._fail_run(
                    stream_error.get("error_type") or RuntimeErrorType.LLM_ERROR.value,
                    stream_error.get("message") or "LLM 流式调用失败",
                )
                raise AgentRuntimeError(
                    RuntimeErrorType.LLM_ERROR,
                    stream_error.get("message") or "LLM 流式调用失败",
                    details=stream_error,
                )

            reasoning_content = "".join(reasoning_parts) if reasoning_parts else None
            if stream_tool_calls:
                tool_call_results = [
                    ToolCallResult(
                        id=tc.get("id") or f"tc_{index}",
                        name=tc["name"],
                        arguments=json.dumps(tc.get("args") or {}, ensure_ascii=False),
                    )
                    for index, tc in enumerate(stream_tool_calls)
                ]
                return (
                    ChatResponse(
                        content="".join(content_parts),
                        tool_calls=tool_call_results,
                        reasoning_content=reasoning_content,
                    ),
                    bool((content_parts and emit_content) or stream_tool_calls),
                )
            return (
                ChatResponse(
                    content="".join(content_parts) if content_parts else None,
                    tool_calls=None,
                    reasoning_content=reasoning_content,
                ),
                bool(content_parts and emit_content),
            )

        raise AssertionError("stream retry loop exhausted")

    def _stream_error_payload(self, data: Any) -> dict[str, Any]:
        if isinstance(data, dict):
            return {
                "message": str(data.get("message") or "LLM 流式调用失败"),
                "error_type": str(data.get("error_type") or RuntimeErrorType.LLM_ERROR.value),
                "retryable": bool(data.get("retryable")),
                "status_code": data.get("status_code"),
            }
        return {
            "message": str(data or "LLM 流式调用失败"),
            "error_type": RuntimeErrorType.LLM_ERROR.value,
            "retryable": False,
            "status_code": None,
        }

    def _stream_error_can_retry(
        self, error: dict[str, Any], emitted: bool, attempt: int
    ) -> bool:
        if attempt or emitted or not error.get("retryable"):
            return False
        if error.get("status_code") in {400, 401, 403, 422}:
            return False
        return error.get("error_type") not in {
            "auth_error",
            "authentication_error",
            "authorization_error",
            "tool_schema_error",
            "reasoning_content_protocol_error",
            "reasoning_protocol_error",
        }

    def _fail_run(self, error_type: str, message: str) -> None:
        self._record_trace(
            TraceEventType.RUN_FAILED,
            {"error_type": error_type, "message": message},
        )
        self._update_run_status(
            RunStatus.FAILED,
            error_type=error_type,
            error_message=message,
        )

    def _return_context_error(
        self, message: str, details: dict[str, Any] | None = None
    ) -> str:
        if details:
            self._record_trace(
                TraceEventType.LLM_CALL_STARTED,
                {**details, "context_error": True, "stage": "context_budget"},
            )
        self._fail_run(RuntimeErrorType.CONTEXT_ERROR.value, message or "context_error")
        return "context_error"

    async def run(self, user_input: str) -> str:
        user_input = sanitize_unicode_text(user_input)
        self._record_trace(
            TraceEventType.RUN_STARTED,
            {"input_length": len(user_input), "conversation_id": self.conversation_id},
        )
        if self.memory_service is not None:
            try:
                bootstrap = self.memory_service.bootstrap_context
                if _call_accepts_keyword(bootstrap, "run_id"):
                    await bootstrap(
                        user_input,
                        self.conversation_id,
                        self.context,
                        run_id=self.run_id,
                        trace_recorder=self.trace_recorder,
                    )
                else:
                    await bootstrap(user_input, self.conversation_id, self.context)
            except Exception:
                logger.exception("长期记忆启动注入失败")
        if self.skill_matcher is not None:
            self.skill_matcher.llm = self.llm
        await self._activate_skills_for_input(user_input)
        await self._ensure_mcp_tools_registered()
        run_message_start = len(self.messages)
        self.messages.append(Message(role=MessageRole.USER, content=user_input))
        self._persist_message(MessageRole.USER, user_input)
        self.context.add_content(
            f"user_{len(self.messages)}",
            user_input,
            ContextLayer.L1,
            token_count=len(user_input) // 4,
        )

        used_tool_names: list[str] = []
        completion_violations = 0

        for iteration in range(self.max_iterations):
            requires_explicit_finish = bool(used_tool_names)
            task_instruction = None
            if requires_explicit_finish:
                task_instruction = (
                    "已经执行过工具。请先观察工具结果并重新判断原始目标："
                    "只能调用一个下一步工具，或调用 finish_task 结束；禁止直接输出普通最终文本。"
                )
                if completion_violations:
                    task_instruction += "上一次没有遵守该协议，请本轮必须调用工具或 finish_task。"
            tool_defs = self.tools.list_definitions()
            selection_context = self._build_tool_selection_context(user_input, used_tool_names)
            exposed_tool_defs = select_llm_tools(tool_defs, context=selection_context)
            dropped_mcp_count = sum(
                1
                for tool in tool_defs
                if tool.category == "mcp"
                and all(exposed_tool.name != tool.name for exposed_tool in exposed_tool_defs)
            )
            try:
                all_messages, budget = self._prepare_llm_messages(
                    self._build_messages(task_instruction),
                    exposed_tool_defs,
                    run_message_start=run_message_start,
                )
            except AgentRuntimeError as exc:
                if exc.error_type == RuntimeErrorType.CONTEXT_ERROR:
                    return self._return_context_error(exc.message, exc.details)
                raise
            self._record_llm_call_started(
                budget,
                {
                    "message_count": len(all_messages),
                    "tool_count": len(exposed_tool_defs),
                    "registered_tool_count": len(tool_defs),
                    "exposed_tool_count": len(exposed_tool_defs),
                    "dropped_mcp_count": dropped_mcp_count,
                    "iteration": iteration,
                    "stage": "answer",
                },
            )

            emitted_from_stream = False
            if self.on_token is not None:
                response, emitted_from_stream = await self._chat_stream_with_retry(
                    all_messages,
                    exposed_tool_defs if exposed_tool_defs else None,
                    emit_content=not requires_explicit_finish,
                )
                if (
                    not requires_explicit_finish
                    and not emitted_from_stream
                    and response.content
                    and not response.tool_calls
                    and self.on_token is not None
                ):
                    await self.on_token(response.content)
            else:
                try:
                    response = await self.llm.chat(
                        all_messages,
                        tools=exposed_tool_defs if exposed_tool_defs else None,
                    )
                except LLMError as exc:
                    self._fail_run(exc.error_type, exc.message)
                    raise
            self._record_trace(
                TraceEventType.LLM_CALL_FINISHED,
                {
                    "has_content": bool(response.content),
                    "tool_call_count": len(response.tool_calls or []),
                    "iteration": iteration,
                },
            )

            if response.content and not response.tool_calls and requires_explicit_finish:
                completion_violations += 1
                self._record_trace(
                    TraceEventType.LLM_PARSE_ERROR,
                    {
                        "stage": "task_completion",
                        "reason": "工具执行后必须调用下一工具或 finish_task",
                        "iteration": iteration,
                    },
                )
                continue

            if response.content and not response.tool_calls:
                response_content = sanitize_unicode_text(response.content)
                return await self._complete_response(
                    response_content,
                    reasoning_content=response.reasoning_content,
                    emit_token=not emitted_from_stream,
                )

            if response.tool_calls:
                tool_calls = [self._tool_call_to_dict(tc) for tc in response.tool_calls]
                self.messages.append(
                    Message(
                        role=MessageRole.ASSISTANT,
                        content=response.content,
                        tool_calls=tool_calls,
                        reasoning_content=response.reasoning_content,
                    )
                )
                self._persist_message(
                    MessageRole.ASSISTANT,
                    response.content or "",
                    tool_calls=tool_calls,
                    intermediate=True,
                    reasoning_content=response.reasoning_content,
                )

                first_tool_call = response.tool_calls[0]
                result = await self._execute_tool_call_result(first_tool_call)
                if first_tool_call.name == "finish_task" and result.success:
                    status = str(result.metadata.get("task_status") or "complete")
                    self._record_trace(
                        TraceEventType.TASK_COMPLETION_DECIDED,
                        {
                            "status": status,
                            "iteration": iteration,
                            "executed_tool_count": len(used_tool_names),
                            "has_missing_information": bool(
                                result.metadata.get("missing_information")
                            ),
                        },
                    )
                    return await self._complete_response(
                        result.output,
                        reasoning_content=response.reasoning_content,
                        emit_token=True,
                    )
                used_tool_names.append(first_tool_call.name)

                for skipped_call in response.tool_calls[1:]:
                    await self._record_tool_result(
                        skipped_call,
                        ToolResult(
                            success=False,
                            output="",
                            error="本轮仅执行一个动作，请观察当前结果后重新决定。",
                            metadata={"skipped": True},
                        ),
                        0,
                    )

            if not response.content and not response.tool_calls:
                if requires_explicit_finish:
                    completion_violations += 1
                    self._record_trace(
                        TraceEventType.LLM_PARSE_ERROR,
                        {
                            "stage": "task_completion",
                            "reason": "工具执行后未返回下一步动作",
                            "iteration": iteration,
                        },
                    )
                    continue
                fallback = "I couldn't generate a response. Please try again."
                if self.on_token is not None:
                    await self.on_token(fallback)
                self.messages.append(
                    Message(role=MessageRole.ASSISTANT, content=fallback, reasoning_content="")
                )
                self._persist_message(MessageRole.ASSISTANT, fallback, reasoning_content="")
                self._record_trace(
                    TraceEventType.RUN_COMPLETED,
                    {"output_length": len(fallback)},
                )
                self._update_run_status(RunStatus.COMPLETED, final_output=fallback)
                return fallback

        self.context.compress_l3()
        message = "已达到最大迭代次数。请改写请求，或把任务拆成更小的步骤后重试。"
        if self.on_token is not None:
            await self.on_token(message)
        self.messages.append(
            Message(role=MessageRole.ASSISTANT, content=message, reasoning_content="")
        )
        self._persist_message(MessageRole.ASSISTANT, message, reasoning_content="")
        self._record_trace(
            TraceEventType.RUN_FAILED,
            {
                "error_type": RuntimeErrorType.MAX_ITERATIONS_REACHED.value,
                "message": message,
            },
        )
        self._update_run_status(
            RunStatus.FAILED,
            error_type=RuntimeErrorType.MAX_ITERATIONS_REACHED.value,
            error_message=message,
        )
        return message

    async def _complete_response(
        self,
        response_content: str,
        *,
        reasoning_content: str | None = None,
        emit_token: bool = False,
    ) -> str:
        if emit_token and self.on_token is not None:
            await self.on_token(response_content)
        self.messages.append(
            Message(
                role=MessageRole.ASSISTANT,
                content=response_content,
                reasoning_content=reasoning_content,
            )
        )
        self.context.add_content(
            f"assistant_{len(self.messages)}",
            response_content,
            ContextLayer.L1,
            token_count=len(response_content) // 4,
        )
        self._persist_message(
            MessageRole.ASSISTANT,
            response_content,
            reasoning_content=reasoning_content,
        )
        self._record_trace(
            TraceEventType.RUN_COMPLETED,
            {"output_length": len(response_content)},
        )
        self._update_run_status(RunStatus.COMPLETED, final_output=response_content)
        return response_content

    def _build_tool_selection_context(
        self, user_input: str, used_tool_names: list[str] | None = None
    ) -> ToolSelectionContext:
        if self.skill_manager is None:
            return ToolSelectionContext(
                user_input=user_input,
                used_tool_names=tuple(used_tool_names or ()),
            )

        active_names = tuple(self.skill_manager.active_skill_names)
        active_metadata = [
            self.skill_manager.skills[name]
            for name in active_names
            if name in self.skill_manager.skills
        ]
        allowed_tools = tuple(
            allowed_tool
            for metadata in active_metadata
            for allowed_tool in metadata.allowed_tools
        )
        descriptions = tuple(metadata.description for metadata in active_metadata)
        return ToolSelectionContext(
            user_input=user_input,
            active_skill_names=active_names,
            active_skill_descriptions=descriptions,
            active_skill_allowed_tools=allowed_tools,
            used_tool_names=tuple(used_tool_names or ()),
        )

    async def _execute_tool_call_result(self, tc: ToolCallResult) -> ToolResult:
        try:
            params = json.loads(tc.arguments)
        except (json.JSONDecodeError, TypeError) as error:
            self._record_trace(
                TraceEventType.LLM_PARSE_ERROR,
                {"stage": "tool_arguments", "tool_name": tc.name, "reason": str(error)},
            )
            raise AgentRuntimeError(
                RuntimeErrorType.LLM_PARSE_ERROR,
                "工具调用参数 JSON 无效",
                recoverable=True,
            ) from error
        if not isinstance(params, dict):
            self._record_trace(
                TraceEventType.LLM_PARSE_ERROR,
                {"stage": "tool_arguments", "tool_name": tc.name, "reason": "参数必须是 JSON 对象"},
            )
            raise AgentRuntimeError(
                RuntimeErrorType.LLM_PARSE_ERROR,
                "工具调用参数 JSON 无效",
                recoverable=True,
            )

        logger.info(f"Tool call: {tc.name}({params})")
        definition = self.tools.get_definition(tc.name)
        canonical_name = self.tools.get_canonical_name(tc.name)
        self._record_trace(
            TraceEventType.TOOL_REQUESTED,
            {
                "tool_name": tc.name,
                "canonical_name": canonical_name,
                "param_keys": sorted(params.keys()),
            },
        )
        if self.on_tool_call is not None:
            await self.on_tool_call(tc.name, params)

        started_at = perf_counter()
        policy_result = self._evaluate_tool_policy(definition, tc.name, canonical_name, params)
        if policy_result is not None:
            self._record_trace(
                TraceEventType.TOOL_POLICY_DECISION,
                {
                    "tool_name": tc.name,
                    "canonical_name": canonical_name,
                    "action": policy_result.action.value,
                    "reason": policy_result.reason,
                    "risk_level": policy_result.risk_level,
                    "matched_rule": policy_result.matched_rule,
                },
            )
            if policy_result.action in {PolicyAction.ASK, PolicyAction.DENY}:
                result = ToolResult(
                    success=False,
                    output="",
                    error=policy_result.reason,
                    metadata={
                        "policy_action": policy_result.action.value,
                        "matched_rule": policy_result.matched_rule,
                    },
                )
                duration_ms = (perf_counter() - started_at) * 1000
                await self._record_tool_result(tc, result, duration_ms)
                return result

        try:
            result = await self.tools.execute(tc.name, params)
        except KeyError:
            result = ToolResult(
                success=False,
                output="",
                error=f"Unknown tool: {tc.name}",
                metadata={"error_type": RuntimeErrorType.TOOL_ERROR.value},
            )
        except Exception as e:
            result = ToolResult(
                success=False,
                output="",
                error=str(e),
                metadata={"error_type": RuntimeErrorType.TOOL_ERROR.value},
            )
        duration_ms = (perf_counter() - started_at) * 1000
        await self._record_tool_result(tc, result, duration_ms)
        return result

    async def _prepare_tool_call(
        self,
        tool_name: str,
        params: dict[str, Any] | None,
        *,
        status: str = "ready",
    ) -> None:
        if not tool_name:
            return

        definition = self.tools.get_definition(tool_name)
        canonical_name = self.tools.get_canonical_name(tool_name)
        metadata: dict[str, Any] = {
            "canonical_name": canonical_name,
            "status": status,
            "has_args": params is not None,
            "read_only": definition.read_only if definition is not None else None,
            "risk_level": definition.risk_level if definition is not None else "unknown",
            "category": definition.category if definition is not None else "unknown",
        }
        if definition is None:
            metadata["status"] = "unknown_tool"

        if tool_name == "activate_skill":
            metadata["kind"] = "skill"
            skill_name = str((params or {}).get("name") or "").strip()
            metadata["skill_name"] = skill_name
            if self.skill_manager is None:
                metadata["status"] = "disabled"
            elif not skill_name:
                metadata["status"] = "missing_args" if params is not None else status
            elif params is not None:
                skill_definition = self.skill_manager.prepare(skill_name)
                if skill_definition is None:
                    metadata["status"] = "unknown_skill"
                else:
                    metadata["status"] = "ready"
                    metadata["prepared_context_length"] = len(
                        self.skill_manager._format_skill_context(skill_definition)
                    )
        else:
            metadata["kind"] = "tool"

        if self.on_tool_prepare is not None:
            await self.on_tool_prepare(tool_name, params, metadata)

    async def _record_tool_result(
        self, tc: ToolCallResult, result: ToolResult, duration_ms: float
    ) -> None:
        if self.memory_service is not None and hasattr(self.memory_service, "record_tool_usage"):
            try:
                self.memory_service.record_tool_usage(
                    tc.name,
                    success=result.success,
                    duration_ms=duration_ms,
                    error=result.error,
                    run_id=self.run_id,
                )
            except Exception:
                logger.exception("记录工具使用统计失败")
        if self.on_tool_result is not None:
            await self.on_tool_result(tc.name, result)

        raw_tool_output = result.output if result.success else f"Error: {result.error}"
        tool_output = sanitize_unicode_text(raw_tool_output)
        self.messages.append(
            Message(
                role=MessageRole.TOOL,
                content=tool_output,
                tool_call_id=tc.id,
                name=tc.name,
            )
        )
        self._persist_message(
            MessageRole.TOOL,
            tool_output,
            tool_name=tc.name,
            tool_call_id=tc.id,
            intermediate=True,
        )
        self.context.add_content(
            f"tool_{tc.id}",
            tool_output,
            ContextLayer.L3,
            token_count=len(tool_output) // 4,
        )
        self._run_compression_pipeline()
        error_type = result.metadata.get("error_type") if result.metadata else None
        if error_type is None and not result.success:
            error_type = (
                RuntimeErrorType.TOOL_TIMEOUT.value
                if result.error and "timed out" in result.error.lower()
                else RuntimeErrorType.TOOL_ERROR.value
            )
        self._record_trace(
            TraceEventType.TOOL_RESULT,
            {
                "tool_name": tc.name,
                "success": result.success,
                "duration_ms": round(duration_ms, 2),
                "output_length": len(result.output or ""),
                "error_type": error_type,
                "error": result.error,
                "metadata": result.metadata,
            },
        )

    def _run_compression_pipeline(self) -> None:
        store = self.history_store if hasattr(self.history_store, "record_compression_event") else None
        try:
            result = CompressionPipeline(self.context, store, self.config.memory).execute(
                self.conversation_id,
                run_id=self.run_id,
            )
            if result.get("phase") != "none":
                self._record_trace(
                    TraceEventType.CONTEXT_COMPRESSED,
                    {
                        **result,
                        "used_tokens": self.context.used_tokens,
                        "max_tokens": self.context.max_tokens,
                    },
                )
        except Exception:
            logger.exception("上下文压缩管道执行失败")

    def _tool_call_to_dict(self, tc: ToolCallResult) -> dict:
        return {
            "id": tc.id,
            "type": tc.type,
            "function": {
                "name": tc.name,
                "arguments": tc.arguments,
            },
        }

    def _persist_message(
        self,
        role: MessageRole,
        content: str,
        tool_name: str | None = None,
        tool_call_id: str | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
        intermediate: bool = False,
        reasoning_content: str | None = None,
    ) -> None:
        try:
            self.history_store.append_message(
                conversation_id=self.conversation_id,
                source=self.source,
                role=role.value,
                content=content,
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                tool_calls=tool_calls,
                intermediate=intermediate,
                reasoning_content=reasoning_content,
            )
        except Exception:
            logger.exception("写入对话历史失败")

    def _new_conversation_id(self) -> str:
        return uuid4().hex

    async def chat(self, user_input: str) -> str:
        return await self.run(user_input)

    def reset(self) -> None:
        self.messages.clear()
        self.conversation_id = self._new_conversation_id()
        self.context = ContextManager(
            max_tokens=self.config.context.max_context_tokens,
            l1_budget_ratio=self.config.context.l1_budget_ratio,
            l2_budget_ratio=self.config.context.l2_budget_ratio,
            l3_budget_ratio=self.config.context.l3_budget_ratio,
            reserve_ratio=self.config.context.reserve_ratio,
        )
        if self.config.skills.enabled:
            self.skill_manager = self._create_skill_manager()
            self.skill_matcher = SkillMatcher(self.llm)
            if self.services is not None and self.services.skill_catalog is not None:
                self.skill_manager.catalog = self.services.skill_catalog
                self.skill_manager.inject_catalog()
            else:
                self.skill_manager.discover()
            self._register_activate_skill_tool()

    async def _activate_skills_for_input(self, user_input: str) -> None:
        if self.skill_manager is None or self.skill_matcher is None:
            return

        explicit_result = self.skill_matcher.match_explicit(user_input, self.skill_manager.skills)
        for unknown_name in explicit_result.unknown_names:
            logger.warning(f"用户显式调用了未知 Skill: {unknown_name}")

        explicit_names = {match.name for match in explicit_result.matches}
        matches = explicit_result.matches
        if not matches and self.config.skills.implicit_match_enabled:
            implicit_result = await self.skill_matcher.match_implicit(
                user_input, self.skill_manager.skills
            )
            matches = implicit_result.matches

        for match in matches[: self.config.skills.max_active]:
            self._activate_skill_by_name(
                match.name,
                activation_type="explicit" if match.name in explicit_names else "implicit",
                reason=match.reason,
            )

    def _activate_skill_by_name(
        self,
        name: str,
        *,
        activation_type: str,
        reason: str | None = None,
    ) -> ToolResult:
        if self.skill_manager is None:
            return ToolResult(
                success=False,
                output="",
                error="Skill 系统未启用。",
                metadata={"activation_type": activation_type},
            )

        definition = self.skill_manager.activate(name)
        if definition is None:
            return ToolResult(
                success=False,
                output="",
                error=f"未知 Skill: {name}",
                metadata={"activation_type": activation_type},
            )

        if self.memory_service is not None and hasattr(self.memory_service, "record_skill_usage"):
            try:
                self.memory_service.record_skill_usage(
                    name,
                    activation_type=activation_type,
                    success=None,
                    run_id=self.run_id,
                )
            except Exception:
                logger.exception("记录 Skill 使用统计失败")
        payload = {
            "skill_name": name,
            "activation_type": activation_type,
        }
        if reason:
            payload["reason"] = reason
        self._record_trace(TraceEventType.SKILL_MATCHED, payload)
        return ToolResult(
            success=True,
            output=f"已激活 Skill: {name}",
            metadata={"activation_type": activation_type, "skill_name": name},
        )

    def _evaluate_tool_policy(
        self,
        definition: ToolDefinition | None,
        tool_name: str,
        canonical_name: str,
        params: dict[str, Any],
    ):
        if self.tool_policy_engine is None:
            return None
        try:
            return self.tool_policy_engine.evaluate(
                definition,
                params,
                ToolPolicyContext(
                    conversation_id=self.conversation_id,
                    run_id=self.run_id,
                    source=self.source,
                    tool_name=tool_name,
                    canonical_name=canonical_name,
                ),
            )
        except Exception:
            logger.exception("工具策略判断失败，降级为拒绝执行")
            from lifeops.runtime.policy import ToolPolicyResult

            return ToolPolicyResult(
                action=PolicyAction.DENY,
                reason="工具策略判断失败，已拒绝执行。",
                risk_level="high",
                matched_rule="policy_error",
            )

    def _record_trace(
        self, event_type: TraceEventType | str, payload: dict[str, Any] | None = None
    ) -> None:
        if self.trace_recorder is None or not self.run_id:
            return
        try:
            self.trace_recorder.record(event_type, payload or {}, run_id=self.run_id)
        except Exception:
            logger.exception("写入 runtime trace 失败")

    def _update_run_status(
        self,
        status: RunStatus,
        *,
        final_output: str | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> None:
        if self.trace_recorder is None or not self.run_id:
            return
        store = getattr(self.trace_recorder, "store", None)
        if store is None or not hasattr(store, "update_run_status"):
            return
        try:
            store.update_run_status(
                self.run_id,
                status,
                final_output=final_output,
                error_type=error_type,
                error_message=error_message,
            )
        except Exception:
            logger.exception("更新 runtime run 状态失败")


def _should_skip_pytest_env_mcp(presets: str) -> bool:
    if "PYTEST_CURRENT_TEST" not in os.environ:
        return False
    return bool(presets.strip())


def _call_accepts_keyword(callable_obj: Any, name: str) -> bool:
    try:
        signature = inspect.signature(callable_obj)
    except (TypeError, ValueError):
        return True
    return name in signature.parameters or any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )
