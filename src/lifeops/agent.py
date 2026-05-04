from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha1
from typing import Any
from uuid import uuid4

from lifeops.core.config import AppConfig
from lifeops.core.context_manager import ContextLayer, ContextManager
from lifeops.history import ConversationHistoryStore, HistorySource
from lifeops.llm.client import LLMClient
from lifeops.llm.types import ChatResponse, Message, MessageRole, ToolCallResult
from lifeops.skills.manager import SkillManager
from lifeops.skills.matcher import SkillMatcher
from lifeops.tools.base import ToolDefinition, ToolParams, ToolResult
from lifeops.tools.builtin import register_all_builtin_tools
from lifeops.tools.mcp.manager import MCPManager
from lifeops.tools.mcp.types import MCPServerConfig
from lifeops.tools.registry import ToolRegistry
from lifeops.utils.logging import get_logger
from lifeops.utils.text import sanitize_unicode_text

logger = get_logger(__name__)


@dataclass(frozen=True)
class RetrievalRouteDecision:
    should_use_rag: bool
    should_use_web: bool
    rag_query: str | None
    web_query: str | None
    reason: str


@dataclass(frozen=True)
class RagSufficiencyDecision:
    is_sufficient: bool
    missing_information: str
    web_query: str | None

DEFAULT_SYSTEM_PROMPT = """# 身份与目标

你是 LifeOps，一个面向个人生活管理的 AI 助理。你帮助用户整理任务、日程、健康、财务、资料、长期目标和个人工作流，把模糊想法转化为可执行的下一步。

# 工作方式

- 先判断用户意图和任务复杂度：简单问题直接回答；复杂任务先拆解关键步骤，再推进。
- 信息不足且会影响结果时，先提出必要的澄清问题；可以基于合理假设继续时，明确说明假设。
- 输出以行动为导向，优先给结论、步骤、清单或可直接使用的文本。
- 解决复杂问题时按步骤思考，但不要暴露内部推理过程，只呈现必要依据和结果。

# 上下文使用

- 优先利用当前对话历史、L1 常驻上下文、L2 已激活 Skill 和 L3 工具结果。
- 不臆造上下文中没有的信息；不确定时说明不确定性，并给出可验证的下一步。
- 当上下文之间冲突时，优先遵循用户最新明确指令；必要时指出冲突并请用户确认。

# 工具使用策略

- 需要读取或编辑本地文件、执行命令、搜索互联网、调用 MCP 或其他外部服务时，使用可用工具完成。
- 检索类问题由系统在回答前按“结构化意图判断 → 本地知识库检索 → 充分性判断 → 必要时网络搜索”的顺序编排；回答阶段基于已注入上下文融合结果，不重复描述内部编排过程。
- 当系统已提供本地知识库或网络搜索结果时，优先使用这些上下文；只有仍需读取文件、执行命令、调用 MCP 或其他非检索工具时，才继续调用对应工具。
- 调用工具前明确目标；工具结果返回后综合判断，不机械复述原始输出。
- 工具调用失败、信息缺失或权限受限时，说明限制、已尝试内容和下一步选择。
- 不为可直接回答的常识性或低风险问题过度调用工具。

# Skill 协作

- 如果系统上下文中出现已激活 Skill，遵循 Skill 正文的工作流、约束和输出要求。
- Skill 与用户最新指令冲突时，以用户最新指令为准；冲突会影响任务质量时，简要说明。
- 不主动编造未激活或不存在的 Skill 内容。

# 安全与边界

- 不协助违法、危险、侵犯隐私、绕过安全控制、泄露凭证或滥用外部服务的请求。
- 涉及健康、财务、法律等高风险事项时，提供一般性信息和决策框架，提示不确定性，并建议用户核验或咨询专业人士。
- 处理个人数据、账号、文件和外部服务时，只执行用户授权范围内的操作。

# 语气与输出

- 始终优先使用中文，表达直接、清晰、克制，少寒暄。
- 需要计划时给短计划；需要结果时给结论和行动项。
- 保持稳定、可靠的语气，不夸大能力，不承诺无法验证的结果。"""


class Agent:
    def __init__(
        self,
        config: AppConfig,
        system_prompt: str | None = None,
        history_store: ConversationHistoryStore | None = None,
        source: HistorySource = "web",
        conversation_id: str | None = None,
    ):
        self.config = config
        self.llm = LLMClient(
            api_key=config.llm.api_key,
            model=config.llm.model,
            api_base=config.llm.api_base,
            max_tokens=config.llm.max_tokens,
            temperature=config.llm.temperature,
            timeout=config.llm.timeout,
        )
        self.tools = ToolRegistry()
        self.mcp_manager = MCPManager()
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
        self.skill_manager: SkillManager | None = None
        self.skill_matcher: SkillMatcher | None = None
        self.rag_retriever: Any | None = None
        self._mcp_tools_registered = False
        self.history_store = history_store or ConversationHistoryStore(config.history_path)
        self.source = source
        self.conversation_id = conversation_id or self._new_conversation_id()

        if config.rag.enabled:
            from lifeops.rag.retriever import RAGRetriever

            self.rag_retriever = RAGRetriever(config.rag)

        self._register_default_tools()
        self._register_rag_tool()

        # MCP 静态配置加载
        if config.mcp.enabled and config.mcp.servers.strip():
            self.mcp_manager.load_from_config(config.mcp.servers)

        self.context.add_content(
            "system_prompt",
            self.system_prompt,
            ContextLayer.L1,
            token_count=len(self.system_prompt) // 4,
        )
        if config.skills.enabled:
            self.skill_manager = SkillManager(
                context=self.context,
                project_dir=config.skills.project_dir,
                user_dir=config.skills.user_dir,
                max_active=config.skills.max_active,
            )
            self.skill_matcher = SkillMatcher(self.llm)
            self.skill_manager.discover()

    def _register_default_tools(self) -> None:
        register_all_builtin_tools(self.tools, self.config)

    def _register_rag_tool(self) -> None:
        if not self.config.rag.enabled:
            return

        from pydantic import Field

        class RetrieveKnowledgeParams(ToolParams):
            query: str
            data_type: str | None = None
            top_files: int = Field(default=3, ge=1)

        async def handler(params: dict[str, Any]) -> ToolResult:
            from lifeops.rag.router import discover_rag_data_types, route_rag_query

            validated = RetrieveKnowledgeParams.model_validate(params)
            if self.rag_retriever is None:
                return ToolResult(success=False, output="", error="RAG 检索器未初始化")

            top_files = min(validated.top_files, 3)
            data_types = discover_rag_data_types(self.config.rag)
            route_plan = route_rag_query(
                validated.query,
                data_types,
                data_type=validated.data_type,
            )
            results = self.rag_retriever.retrieve(
                validated.query,
                domain=route_plan.domain,
                category=route_plan.category,
                path_prefix=route_plan.path_prefix,
                top_files=top_files,
            )
            formatted = self.rag_retriever.format_results(results)
            route_key = route_plan.data_type or route_plan.domain or "all"
            query_hash = sha1(validated.query.encode("utf-8")).hexdigest()[:12]
            self.context.add_content(
                f"rag:{route_key}:{query_hash}",
                formatted,
                ContextLayer.L2,
                token_count=len(formatted) // 4,
            )
            return ToolResult(
                success=True,
                output=formatted,
                metadata={
                    "selected_data_type": route_plan.data_type,
                    "path_prefix": route_plan.path_prefix,
                    "result_count": len(results),
                    "top_files": top_files,
                    "route_reason": route_plan.reason,
                },
            )

        from lifeops.rag.router import discover_rag_data_types, format_data_type_catalog

        catalog = format_data_type_catalog(discover_rag_data_types(self.config.rag))
        self.tools.register(
            ToolDefinition(
                name="retrieve_knowledge",
                description=(
                    "知识库路由检索：从本地知识库自动选择合适的数据类型和检索范围，"
                    "适合查询食谱、做法、食材、替代方案、已有笔记或个人知识库内容；"
                    "最多返回 3 个文件级结果。可选 data_type 用于明确指定范围。\n"
                    f"{catalog}"
                ),
                parameters_model=RetrieveKnowledgeParams,
                category="builtin",
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

    def _build_messages(self) -> list[Message]:
        result = [Message(role=MessageRole.SYSTEM, content=self._build_system_context())]
        result.extend(self.messages)
        return result

    def _build_system_context(self) -> str:
        sections: list[str] = []
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
        return "\n\n".join(sections) if sections else self.system_prompt

    async def run(self, user_input: str) -> str:
        user_input = sanitize_unicode_text(user_input)
        if self.skill_matcher is not None:
            self.skill_matcher.llm = self.llm
        await self._activate_skills_for_input(user_input)
        await self._ensure_mcp_tools_registered()
        self.messages.append(Message(role=MessageRole.USER, content=user_input))
        self._persist_message(MessageRole.USER, user_input)
        self.context.add_content(
            f"user_{len(self.messages)}",
            user_input,
            ContextLayer.L1,
            token_count=len(user_input) // 4,
        )

        first_response = await self._orchestrate_retrieval_before_answer(user_input)

        for iteration in range(self.max_iterations):
            all_messages = self._build_messages()
            tool_defs = self.tools.list_definitions()

            if iteration == 0 and first_response is not None:
                response = first_response
            else:
                response = await self.llm.chat(all_messages, tools=tool_defs if tool_defs else None)

            if response.content and not response.tool_calls:
                response_content = sanitize_unicode_text(response.content)
                self.messages.append(Message(role=MessageRole.ASSISTANT, content=response_content))
                self.context.add_content(
                    f"assistant_{len(self.messages)}",
                    response_content,
                    ContextLayer.L1,
                    token_count=len(response_content) // 4,
                )
                self._persist_message(MessageRole.ASSISTANT, response_content)
                return response_content

            if response.tool_calls:
                tool_calls = [self._tool_call_to_dict(tc) for tc in response.tool_calls]
                self.messages.append(
                    Message(
                        role=MessageRole.ASSISTANT,
                        content=response.content,
                        tool_calls=tool_calls,
                    )
                )
                self._persist_message(
                    MessageRole.ASSISTANT,
                    response.content or "",
                    tool_calls=tool_calls,
                    intermediate=True,
                )

                for tc in response.tool_calls:
                    await self._execute_tool_call_result(tc)

            if not response.content and not response.tool_calls:
                return "I couldn't generate a response. Please try again."

        self.context.compress_l3()
        return "I reached the maximum number of iterations. Please rephrase your request or break it into smaller steps."

    async def _orchestrate_retrieval_before_answer(
        self, user_input: str
    ) -> ChatResponse | None:
        route_decision, fallback_response = await self._plan_retrieval_route(user_input)
        if route_decision is None:
            return fallback_response

        rag_result: ToolResult | None = None
        rag_was_requested = route_decision.should_use_rag
        rag_is_available = self.tools.get_definition("retrieve_knowledge") is not None
        if rag_was_requested and rag_is_available:
            rag_query = route_decision.rag_query or user_input
            rag_result = await self._execute_pre_answer_tool(
                "retrieve_knowledge",
                {"query": rag_query},
            )

        should_use_web = route_decision.should_use_web
        web_query = route_decision.web_query
        if rag_result is not None and rag_result.success:
            sufficiency_decision = await self._evaluate_rag_sufficiency(user_input, rag_result)
            if sufficiency_decision is not None and not sufficiency_decision.is_sufficient:
                should_use_web = True
                web_query = sufficiency_decision.web_query or web_query
        elif rag_was_requested and not rag_is_available:
            should_use_web = True
            web_query = web_query or route_decision.rag_query or user_input
        elif rag_result is not None and not rag_result.success:
            should_use_web = True
            web_query = web_query or route_decision.rag_query or user_input

        if should_use_web and self.tools.get_definition("web_search") is not None:
            await self._execute_pre_answer_tool(
                "web_search",
                {"query": web_query or user_input},
            )

        return None

    async def _plan_retrieval_route(
        self, user_input: str
    ) -> tuple[RetrievalRouteDecision | None, ChatResponse | None]:
        prompt = (
            "请判断回答用户问题前是否需要检索。只输出 JSON 对象，不要输出 Markdown。\n"
            "字段：should_use_rag(boolean), should_use_web(boolean), "
            "rag_query(string|null), web_query(string|null), reason(string)。\n"
            "判断原则：\n"
            "- 涉及用户本地知识库、已有文档、食谱、笔记、个人资料时 should_use_rag=true。\n"
            "- 涉及最新信息、外部事实、价格、政策、新闻、网页资料时 should_use_web=true。\n"
            "- 常识、闲聊、无需额外资料的任务两个字段都为 false。\n\n"
            f"用户问题：{user_input}"
        )
        response = await self.llm.chat(
            self._build_messages() + [Message(role=MessageRole.USER, content=prompt)],
            tools=None,
        )
        if response.tool_calls:
            return None, response

        payload = self._parse_json_object(response.content)
        if payload is None:
            return None, None

        try:
            return (
                RetrievalRouteDecision(
                    should_use_rag=self._coerce_bool(payload.get("should_use_rag")),
                    should_use_web=self._coerce_bool(payload.get("should_use_web")),
                    rag_query=self._optional_text(payload.get("rag_query")),
                    web_query=self._optional_text(payload.get("web_query")),
                    reason=str(payload.get("reason") or ""),
                ),
                None,
            )
        except Exception:
            logger.exception("检索路由结构化结果解析失败")
            return None, None

    async def _evaluate_rag_sufficiency(
        self, user_input: str, rag_result: ToolResult
    ) -> RagSufficiencyDecision | None:
        prompt = (
            "请判断以下本地知识库检索结果是否足够回答用户问题。只输出 JSON 对象，"
            "不要输出 Markdown。\n"
            "字段：is_sufficient(boolean), missing_information(string), web_query(string|null)。\n"
            "如果本地资料不足且需要外部补充，请给出适合网络搜索的 web_query。\n\n"
            f"用户问题：{user_input}\n\n"
            f"本地知识库结果：\n{rag_result.output}"
        )
        response = await self.llm.chat(
            self._build_messages() + [Message(role=MessageRole.USER, content=prompt)],
            tools=None,
        )
        payload = self._parse_json_object(response.content)
        if payload is None:
            return None

        try:
            return RagSufficiencyDecision(
                is_sufficient=self._coerce_bool(payload.get("is_sufficient")),
                missing_information=str(payload.get("missing_information") or ""),
                web_query=self._optional_text(payload.get("web_query")),
            )
        except Exception:
            logger.exception("RAG 充分性结构化结果解析失败")
            return None

    async def _execute_pre_answer_tool(
        self, tool_name: str, params: dict[str, Any]
    ) -> ToolResult:
        tool_call = ToolCallResult(
            id=f"pre_{uuid4().hex}",
            name=tool_name,
            arguments=json.dumps(params, ensure_ascii=False),
            type="function",
        )
        tool_calls = [self._tool_call_to_dict(tool_call)]
        self.messages.append(
            Message(
                role=MessageRole.ASSISTANT,
                content=f"准备调用 {tool_name}",
                tool_calls=tool_calls,
            )
        )
        self._persist_message(
            MessageRole.ASSISTANT,
            f"准备调用 {tool_name}",
            tool_calls=tool_calls,
            intermediate=True,
        )
        return await self._execute_tool_call_result(tool_call)

    async def _execute_tool_call_result(self, tc: ToolCallResult) -> ToolResult:
        try:
            params = json.loads(tc.arguments)
        except json.JSONDecodeError:
            params = {}

        logger.info(f"Tool call: {tc.name}({params})")

        try:
            result = await self.tools.execute(tc.name, params)
        except KeyError:
            result = ToolResult(success=False, output="", error=f"Unknown tool: {tc.name}")
        except Exception as e:
            result = ToolResult(success=False, output="", error=str(e))

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
        return result

    def _parse_json_object(self, content: str | None) -> dict[str, Any] | None:
        if not content:
            return None
        text = content.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        return payload

    def _optional_text(self, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _coerce_bool(self, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"true", "1", "yes", "y"}
        return bool(value)

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
        self.context.add_content(
            "system_prompt",
            self.system_prompt,
            ContextLayer.L1,
            token_count=len(self.system_prompt) // 4,
        )
        if self.config.skills.enabled:
            self.skill_manager = SkillManager(
                context=self.context,
                project_dir=self.config.skills.project_dir,
                user_dir=self.config.skills.user_dir,
                max_active=self.config.skills.max_active,
            )
            self.skill_matcher = SkillMatcher(self.llm)
            self.skill_manager.discover()

    async def _activate_skills_for_input(self, user_input: str) -> None:
        if self.skill_manager is None or self.skill_matcher is None:
            return

        explicit_result = self.skill_matcher.match_explicit(user_input, self.skill_manager.skills)
        for unknown_name in explicit_result.unknown_names:
            logger.warning(f"用户显式调用了未知 Skill: {unknown_name}")

        matches = explicit_result.matches
        if not matches and self.config.skills.implicit_match_enabled:
            implicit_result = await self.skill_matcher.match_implicit(
                user_input, self.skill_manager.skills
            )
            matches = implicit_result.matches

        for match in matches[: self.config.skills.max_active]:
            self.skill_manager.activate(match.name)
