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

DEFAULT_SYSTEM_PROMPT = """You are LifeOps, an AI-powered life assistant agent. You help users manage their daily life tasks, schedules, health, finances, and personal goals.

You have access to tools that you can use to help the user. When you need to use a tool, call it with the appropriate parameters. After receiving the tool result, synthesize the information and provide a helpful response.

Key behaviors:
- Be concise and helpful
- Use tools when needed to accomplish tasks
- Think step by step when solving complex problems
- Ask clarifying questions when the user's request is ambiguous
- Remember context from the conversation"""


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

    def add_tool(self, definition: ToolDefinition, handler: Any) -> None:
        self.tools.register(definition, handler)

    def add_mcp_server(self, name: str, config: MCPServerConfig) -> None:
        """动态注册 MCP server 配置。连接和工具注册在 Wave 2 Adapter 中完成。"""
        self.mcp_manager.add_server(name, config)

    def remove_mcp_server(self, name: str) -> None:
        """动态移除 MCP server 配置。工具解绑在 Wave 2 Adapter 中完成。"""
        self.mcp_manager.remove_server(name)

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
                self.messages.append(
                    Message(
                        role=MessageRole.ASSISTANT,
                        content=response.content,
                        tool_calls=[self._tool_call_to_dict(tc) for tc in response.tool_calls],
                    )
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
    ) -> None:
        try:
            self.history_store.append_message(
                conversation_id=self.conversation_id,
                source=self.source,
                role=role.value,
                content=content,
                tool_name=tool_name,
                tool_call_id=tool_call_id,
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
