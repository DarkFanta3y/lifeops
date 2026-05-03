from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from lifeops.agent import Agent
from lifeops.core.config import AppConfig, clear_proxy_env
from lifeops.core.context_manager import ContextManager
from lifeops.history import ConversationHistoryStore
from lifeops.llm.types import Message, MessageRole
from lifeops.skills.loader import _parse_yaml_subset
from lifeops.skills.manager import SkillManager
from lifeops.tools.builtin import register_all_builtin_tools
from lifeops.tools.mcp.manager import MCPManager
from lifeops.tools.mcp.types import MCPToolInfo
from lifeops.tools.registry import ToolRegistry
from lifeops.utils.logging import get_logger
from lifeops.utils.logging import setup_logger
from lifeops.web.title_summary import fallback_conversation_title, summarize_conversation_title

logger = get_logger(__name__)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    conversation_id: str | None = None


class ChatResponse(BaseModel):
    conversation_id: str
    reply: str
    title: str | None = None


class CreateSkillRequest(BaseModel):
    name: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    description: str = Field(min_length=1)
    metadata: str = ""
    content: str = Field(min_length=1)


def create_app(config: AppConfig | None = None) -> FastAPI:
    app_config = config or AppConfig()
    app = FastAPI(title="LifeOps Web API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^http://(localhost|127\.0\.0\.1):\d+$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.config = app_config
    app.state.history_store = ConversationHistoryStore(app_config.history_path)
    app.state.web_agents = {}
    app.state.tool_registry = ToolRegistry()
    register_all_builtin_tools(app.state.tool_registry, app_config)
    app.state.mcp_manager = MCPManager()
    if app_config.mcp.enabled and app_config.mcp.servers.strip():
        app.state.mcp_manager.load_from_config(app_config.mcp.servers)

    @app.get("/api/conversations")
    async def list_conversations(query: str | None = None) -> dict[str, Any]:
        return {"conversations": app.state.history_store.list_conversations(query)}

    @app.get("/api/conversations/{conversation_id}")
    async def get_conversation(conversation_id: str) -> dict[str, Any]:
        all_messages = app.state.history_store.get_messages(conversation_id)
        messages = [m for m in all_messages if not _is_intermediate_message(m)]
        intermediate_messages = [m for m in all_messages if _is_intermediate_message(m)]
        return {
            "conversation_id": conversation_id,
            "messages": messages,
            "intermediate_messages": intermediate_messages,
        }

    @app.delete("/api/conversations/{conversation_id}")
    async def delete_conversation(conversation_id: str) -> dict[str, Any]:
        deleted_count = app.state.history_store.delete_conversation(conversation_id)
        app.state.web_agents.pop(conversation_id, None)
        return {"conversation_id": conversation_id, "deleted_count": deleted_count}

    @app.post("/api/chat", response_model=ChatResponse)
    async def chat(request: ChatRequest) -> ChatResponse:
        if not app.state.config.llm.api_key:
            raise HTTPException(
                status_code=400,
                detail="LLM_API_KEY 未设置。请在 .env 或环境变量中配置后再启动 Web API。",
            )

        is_new_conversation = request.conversation_id is None
        conversation_id = request.conversation_id or _new_web_conversation_id()
        agent = _get_or_create_web_agent(app, conversation_id)
        if not is_new_conversation:
            reply = await agent.run(request.message)
            title = await _backfill_conversation_title_if_missing(
                app.state.history_store,
                conversation_id,
                agent.llm,
            )
            return ChatResponse(conversation_id=conversation_id, reply=reply, title=title)

        logger.info(f"Web 新会话进入标题生成: conversation_id={conversation_id}")
        reply_task = asyncio.create_task(agent.run(request.message))
        title_task = asyncio.create_task(summarize_conversation_title(agent.llm, request.message))
        reply_result, title_result = await asyncio.gather(
            reply_task,
            title_task,
            return_exceptions=True,
        )
        if isinstance(reply_result, Exception):
            raise reply_result

        title = _resolve_title_result(request.message, title_result, conversation_id)
        app.state.history_store.append_conversation_title(conversation_id, "web", title)
        return ChatResponse(conversation_id=conversation_id, reply=reply_result, title=title)

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

    @app.post("/api/skills", status_code=status.HTTP_201_CREATED)
    async def create_skill(request: CreateSkillRequest) -> dict[str, Any]:
        existing_manager = _discover_skill_manager(app.state.config)
        if request.name in existing_manager.skills:
            raise HTTPException(status_code=409, detail=f"Skill '{request.name}' 已存在。")

        metadata = _parse_metadata_fragment(request.metadata)
        skill_file = _write_project_skill(app.state.config, request, metadata)
        return {"name": request.name, "path": str(skill_file)}

    @app.get("/api/tools")
    async def list_tools() -> dict[str, Any]:
        registry: ToolRegistry = app.state.tool_registry
        mcp_servers = await _connect_and_describe_mcp_servers(app.state.mcp_manager, registry)
        tools = [
            {
                "name": tool.name,
                "description": tool.description,
                "category": tool.category,
                "parameters": _parameters_schema(tool.parameters_model.model_json_schema()),
            }
            for tool in registry.list_definitions()
        ]
        return {"tools": tools, "mcp_servers": mcp_servers}

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
        if _is_intermediate_message(record):
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


def _is_intermediate_message(record: dict[str, Any]) -> bool:
    role = record.get("role")
    if record.get("intermediate") is True:
        return True
    if role == MessageRole.TOOL.value:
        return True
    if role == MessageRole.ASSISTANT.value and record.get("tool_calls") is not None:
        return True
    if role == MessageRole.ASSISTANT.value and (
        record.get("tool_name") or record.get("tool_call_id")
    ):
        return True
    return False


async def _backfill_conversation_title_if_missing(
    history_store: ConversationHistoryStore,
    conversation_id: str,
    llm: Any,
) -> str | None:
    if history_store.has_conversation_title(conversation_id):
        return None

    first_user_message = history_store.get_first_user_message(conversation_id)
    if first_user_message is None:
        return None

    logger.info(f"Web 已有会话缺少标题，触发补生成: conversation_id={conversation_id}")
    try:
        title = await summarize_conversation_title(llm, first_user_message)
    except Exception:
        title = fallback_conversation_title(first_user_message)
        logger.warning(
            f"Web 会话标题补生成失败，使用 fallback: conversation_id={conversation_id}",
            exc_info=True,
        )
    history_store.append_conversation_title(conversation_id, "web", title)
    return title


def _resolve_title_result(
    first_user_message: str,
    title_result: str | BaseException,
    conversation_id: str,
) -> str:
    if not isinstance(title_result, BaseException):
        return title_result

    logger.warning(
        f"Web 新会话标题生成失败，使用 fallback: conversation_id={conversation_id}",
        exc_info=(type(title_result), title_result, title_result.__traceback__),
    )
    return fallback_conversation_title(first_user_message)


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


def _parse_metadata_fragment(raw_metadata: str) -> dict[str, Any]:
    if not raw_metadata.strip():
        return {}
    try:
        metadata = _parse_yaml_subset(raw_metadata.splitlines())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"metadata YAML 无效: {exc}") from exc
    if not isinstance(metadata, dict):
        raise HTTPException(status_code=422, detail="metadata 必须是 YAML mapping。")
    return metadata


def _write_project_skill(
    config: AppConfig, request: CreateSkillRequest, metadata: dict[str, Any]
) -> Path:
    project_root = Path(config.skills.project_dir).expanduser()
    project_root.mkdir(parents=True, exist_ok=True)
    root = project_root.resolve()
    skill_dir = (root / request.name).resolve()
    if not skill_dir.is_relative_to(root):
        raise HTTPException(status_code=422, detail="Skill 名称不能包含路径。")
    if skill_dir.exists():
        raise HTTPException(status_code=409, detail=f"Skill '{request.name}' 已存在。")

    skill_dir.mkdir()
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(_format_skill_file(request, metadata), encoding="utf-8")
    return skill_file


def _format_skill_file(request: CreateSkillRequest, metadata: dict[str, Any]) -> str:
    frontmatter = [
        "---",
        f"name: {request.name}",
        "description: |-",
        *_indent_block(request.description),
    ]
    if metadata:
        frontmatter.append("metadata:")
        frontmatter.extend(_dump_yaml_mapping(metadata, indent=2))
    frontmatter.append("---")
    content = request.content.rstrip()
    return "\n".join(frontmatter) + "\n\n" + content + "\n"


def _indent_block(value: str, spaces: int = 2) -> list[str]:
    prefix = " " * spaces
    return [f"{prefix}{line}" if line else prefix for line in value.strip().splitlines()]


def _dump_yaml_mapping(mapping: dict[str, Any], indent: int = 0) -> list[str]:
    lines: list[str] = []
    prefix = " " * indent
    for key, value in mapping.items():
        if isinstance(value, dict):
            lines.append(f"{prefix}{key}:")
            lines.extend(_dump_yaml_mapping(value, indent + 2))
        elif isinstance(value, list):
            lines.append(f"{prefix}{key}:")
            lines.extend(_dump_yaml_list(value, indent + 2))
        elif isinstance(value, str) and "\n" in value:
            lines.append(f"{prefix}{key}: |-")
            lines.extend(_indent_block(value, indent + 2))
        else:
            lines.append(f"{prefix}{key}: {_dump_yaml_scalar(value)}")
    return lines


def _dump_yaml_list(values: list[Any], indent: int) -> list[str]:
    lines: list[str] = []
    prefix = " " * indent
    for value in values:
        if isinstance(value, dict):
            items = list(value.items())
            if not items:
                lines.append(f"{prefix}- null")
                continue
            first_key, first_value = items[0]
            if isinstance(first_value, dict | list):
                lines.append(f"{prefix}- {first_key}:")
                nested_lines = (
                    _dump_yaml_mapping(first_value, indent + 4)
                    if isinstance(first_value, dict)
                    else _dump_yaml_list(first_value, indent + 4)
                )
                lines.extend(nested_lines)
            else:
                lines.append(f"{prefix}- {first_key}: {_dump_yaml_scalar(first_value)}")
            lines.extend(_dump_yaml_mapping(dict(items[1:]), indent + 2))
        else:
            lines.append(f"{prefix}- {_dump_yaml_scalar(value)}")
    return lines


def _dump_yaml_scalar(value: Any) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "null"
    if isinstance(value, str) and (
        value == ""
        or value in {"true", "True", "false", "False", "null", "Null", "~"}
        or value.startswith(("[", "{"))
    ):
        return f"'{value}'" if value else '""'
    return str(value)


async def _connect_and_describe_mcp_servers(
    manager: MCPManager, registry: ToolRegistry
) -> list[dict[str, Any]]:
    await manager.connect_and_register_all(registry)
    server_groups: list[dict[str, Any]] = []
    for server_name in manager.list_servers():
        client = manager.get_client(server_name)
        if client is None:
            continue
        tools = await client.list_tools()
        if not tools:
            continue
        server_groups.append(
            {
                "name": server_name,
                "tools": [_mcp_tool_payload(tool) for tool in tools],
            }
        )
    return server_groups


def _mcp_tool_payload(tool: MCPToolInfo) -> dict[str, Any]:
    return {
        "name": tool.original_name,
        "description": tool.description,
        "parameters": _parameters_schema(tool.input_schema),
    }


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
