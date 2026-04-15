from __future__ import annotations

import json
from typing import Any

from lifeops.core.config import AppConfig
from lifeops.core.context_manager import ContextLayer, ContextManager
from lifeops.llm.client import LLMClient
from lifeops.llm.types import Message, MessageRole, ToolCallResult
from lifeops.tools.base import ToolDefinition, ToolResult
from lifeops.tools.builtin import register_all_builtin_tools
from lifeops.tools.registry import ToolRegistry
from lifeops.utils.logging import get_logger

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
    def __init__(self, config: AppConfig, system_prompt: str | None = None):
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

        self._register_default_tools()

        self.context.add_content(
            "system_prompt",
            self.system_prompt,
            ContextLayer.L1,
            token_count=len(self.system_prompt) // 4,
        )

    def _register_default_tools(self) -> None:
        register_all_builtin_tools(self.tools, self.config)

    def add_tool(self, definition: ToolDefinition, handler: Any) -> None:
        self.tools.register(definition, handler)

    def _build_messages(self) -> list[Message]:
        result = [Message(role=MessageRole.SYSTEM, content=self.system_prompt)]
        result.extend(self.messages)
        return result

    async def run(self, user_input: str) -> str:
        self.messages.append(Message(role=MessageRole.USER, content=user_input))
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
                self.messages.append(Message(role=MessageRole.ASSISTANT, content=response.content))
                self.context.add_content(
                    f"assistant_{len(self.messages)}",
                    response.content,
                    ContextLayer.L1,
                    token_count=len(response.content) // 4,
                )
                return response.content

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

                    tool_output = result.output if result.success else f"Error: {result.error}"
                    self.messages.append(
                        Message(
                            role=MessageRole.TOOL,
                            content=tool_output,
                            tool_call_id=tc.id,
                            name=tc.name,
                        )
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

    async def chat(self, user_input: str) -> str:
        return await self.run(user_input)

    def reset(self) -> None:
        self.messages.clear()
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


def main() -> None:
    import asyncio

    from rich.console import Console
    from rich.panel import Panel

    from lifeops.core.config import AppConfig, clear_proxy_env
    from lifeops.utils.logging import setup_logger

    clear_proxy_env()

    config = AppConfig()
    setup_logger(level=config.log_level)

    console = Console()

    if not config.llm.api_key:
        console.print("[red]Error: LLM_API_KEY not set.[/red]")
        console.print("[dim]  1. Copy .env.example to .env: cp .env.example .env[/dim]")
        console.print("[dim]  2. Edit .env and set LLM_API_KEY=your-key-here[/dim]")
        console.print(
            "[dim]  Or set it via environment variable: export LLM_API_KEY=your-key-here[/dim]"
        )
        return

    agent = Agent(config)

    console.print(Panel("LifeOps Agent v0.1.0", style="bold green"))
    console.print("[dim]Type 'exit' or 'quit' to end the session.[/dim]")
    console.print("[dim]Type 'reset' to clear conversation history.[/dim]")
    console.print("[dim]Type 'context' to view context usage.[/dim]\n")

    while True:
        try:
            user_input = console.input("[bold blue]You:[/bold blue] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye![/dim]")
            break

        if not user_input:
            continue

        if user_input.lower() in ("exit", "quit"):
            console.print("[dim]Goodbye![/dim]")
            break

        if user_input.lower() == "reset":
            agent.reset()
            console.print("[yellow]Conversation reset.[/yellow]\n")
            continue

        if user_input.lower() == "context":
            summary = agent.context.get_summary()
            console.print(
                Panel(
                    f"Total: {summary['total_used']:,} / {agent.context.max_tokens:,} tokens\n"
                    f"L1: {summary['l1_tokens']:,} tokens ({summary['l1_entries']} entries)\n"
                    f"L2: {summary['l2_tokens']:,} tokens ({summary['l2_entries']} entries)\n"
                    f"L3: {summary['l3_tokens']:,} tokens ({summary['l3_entries']} entries)\n"
                    f"Remaining: {summary['remaining']:,} tokens",
                    title="Context Usage",
                    style="cyan",
                )
            )
            continue

        console.print("[dim]Thinking...[/dim]")

        try:
            response = asyncio.run(agent.run(user_input))
            console.print(Panel(response, title="[bold green]Agent[/bold green]", style="green"))
        except Exception as e:
            console.print(Panel(f"Error: {e}", title="[bold red]Error[/bold red]", style="red"))
            logger.error(f"Agent error: {e}")


if __name__ == "__main__":
    main()
