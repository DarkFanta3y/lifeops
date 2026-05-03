from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from lifeops.core.config import AppConfig
from lifeops.core.context_manager import ContextLayer, ContextManager
from lifeops.history import ConversationHistoryStore, HistorySource
from lifeops.llm.client import LLMClient
from lifeops.llm.types import Message, MessageRole, ToolCallResult
from lifeops.skills.manager import SkillManager
from lifeops.skills.matcher import SkillMatcher
from lifeops.tools.base import ToolDefinition, ToolResult
from lifeops.tools.builtin import register_all_builtin_tools
from lifeops.tools.mcp.manager import MCPManager
from lifeops.tools.mcp.types import MCPServerConfig
from lifeops.tools.registry import ToolRegistry
from lifeops.utils.logging import get_logger
from lifeops.utils.text import sanitize_unicode_text

logger = get_logger(__name__)

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
        self._mcp_tools_registered = False
        self.history_store = history_store or ConversationHistoryStore(config.history_path)
        self.source = source
        self.conversation_id = conversation_id or self._new_conversation_id()

        self._register_default_tools()

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

        for iteration in range(self.max_iterations):
            all_messages = self._build_messages()
            tool_defs = self.tools.list_definitions()

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
                    try:
                        params = json.loads(tc.arguments)
                    except json.JSONDecodeError:
                        params = {}

                    logger.info(f"Tool call: {tc.name}({params})")

                    try:
                        result = await self.tools.execute(tc.name, params)
                    except KeyError:
                        result = ToolResult(
                            success=False, output="", error=f"Unknown tool: {tc.name}"
                        )
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

            if not response.content and not response.tool_calls:
                return "I couldn't generate a response. Please try again."

        self.context.compress_l3()
        return "I reached the maximum number of iterations. Please rephrase your request or break it into smaller steps."

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
