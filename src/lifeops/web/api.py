from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from lifeops.agent import Agent
from lifeops.core.config import AppConfig, clear_proxy_env
from lifeops.core.context_manager import ContextManager
from lifeops.history import ConversationHistoryStore
from lifeops.llm.types import Message, MessageRole
from lifeops.skills.manager import SkillManager
from lifeops.tools.builtin import register_all_builtin_tools
from lifeops.tools.registry import ToolRegistry
from lifeops.utils.logging import setup_logger


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    conversation_id: str | None = None


class ChatResponse(BaseModel):
    conversation_id: str
    reply: str


def create_app(config: AppConfig | None = None) -> FastAPI:
    app_config = config or AppConfig()
    app = FastAPI(title="LifeOps Web API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.config = app_config
    app.state.history_store = ConversationHistoryStore(app_config.history_path)
    app.state.web_agents = {}

    @app.get("/api/conversations")
    async def list_conversations() -> dict[str, Any]:
        return {"conversations": app.state.history_store.list_conversations()}

    @app.get("/api/conversations/{conversation_id}")
    async def get_conversation(conversation_id: str) -> dict[str, Any]:
        return {
            "conversation_id": conversation_id,
            "messages": app.state.history_store.get_messages(conversation_id),
        }

    @app.post("/api/chat", response_model=ChatResponse)
    async def chat(request: ChatRequest) -> ChatResponse:
        if not app.state.config.llm.api_key:
            raise HTTPException(
                status_code=400,
                detail="LLM_API_KEY 未设置。请在 .env 或环境变量中配置后再启动 Web API。",
            )

        conversation_id = request.conversation_id or _new_web_conversation_id()
        agent = _get_or_create_web_agent(app, conversation_id)
        reply = await agent.run(request.message)
        return ChatResponse(conversation_id=conversation_id, reply=reply)

    @app.get("/api/skills")
    async def list_skills() -> dict[str, Any]:
        manager = _discover_skill_manager(app.state.config)
        skills = [
            {
                "name": skill.name,
                "description": skill.description,
                "source": skill.source.value,
                "path": str(skill.path),
                "short_description": skill.short_description,
                "allowed_tools": skill.allowed_tools,
                "dependencies": skill.dependencies,
            }
            for skill in manager.skills.values()
        ]
        return {"skills": skills}

    @app.get("/api/tools")
    async def list_tools() -> dict[str, Any]:
        registry = ToolRegistry()
        register_all_builtin_tools(registry, app.state.config)
        tools = [
            {
                "name": tool.name,
                "description": tool.description,
                "category": tool.category,
                "parameters": _parameters_schema(tool.parameters_model.model_json_schema()),
            }
            for tool in registry.list_definitions()
        ]
        return {"tools": tools}

    return app


def _get_or_create_web_agent(app: FastAPI, conversation_id: str) -> Agent:
    agents: dict[str, Agent] = app.state.web_agents
    if conversation_id in agents:
        return agents[conversation_id]

    agent = Agent(
        app.state.config,
        history_store=app.state.history_store,
        source="web",
        conversation_id=conversation_id,
    )
    agent.messages = _hydrate_messages(app.state.history_store.get_messages(conversation_id))
    agents[conversation_id] = agent
    return agent


def _hydrate_messages(records: list[dict[str, Any]]) -> list[Message]:
    messages: list[Message] = []
    for record in records:
        try:
            role = MessageRole(record["role"])
        except ValueError:
            continue
        if role == MessageRole.SYSTEM:
            continue
        if role == MessageRole.TOOL:
            continue
        messages.append(
            Message(
                role=role,
                content=record.get("content"),
                tool_call_id=record.get("tool_call_id"),
                name=record.get("tool_name"),
            )
        )
    return messages


def _discover_skill_manager(config: AppConfig) -> SkillManager:
    context = ContextManager(
        max_tokens=config.context.max_context_tokens,
        l1_budget_ratio=config.context.l1_budget_ratio,
        l2_budget_ratio=config.context.l2_budget_ratio,
        l3_budget_ratio=config.context.l3_budget_ratio,
        reserve_ratio=config.context.reserve_ratio,
    )
    manager = SkillManager(
        context=context,
        project_dir=config.skills.project_dir,
        user_dir=config.skills.user_dir,
        max_active=config.skills.max_active,
    )
    manager.discover()
    return manager


def _parameters_schema(json_schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": json_schema.get("properties", {}),
        "required": json_schema.get("required", []),
    }


def _new_web_conversation_id() -> str:
    from uuid import uuid4

    return uuid4().hex


def main() -> None:
    import uvicorn

    clear_proxy_env()
    config = AppConfig()
    setup_logger(level=config.log_level)
    uvicorn.run(create_app(config), host="127.0.0.1", port=8081)
