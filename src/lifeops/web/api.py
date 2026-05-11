from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from lifeops.agent import Agent, AgentServices
from lifeops.core.config import PROJECT_ROOT, AppConfig, clear_proxy_env
from lifeops.core.context_manager import ContextManager
from lifeops.llm.types import Message, MessageRole
from lifeops.memory import MemoryService
from lifeops.rag.embeddings import SentenceTransformerEmbeddingProvider
from lifeops.rag.indexer import RAGIndexer
from lifeops.storage import ConversationHistoryStoreSQLite, auto_migrate
from lifeops.skills.loader import _parse_yaml_subset
from lifeops.skills.manager import SkillManager
from lifeops.tools.builtin import register_all_builtin_tools
from lifeops.tools.mcp.manager import MCPManager
from lifeops.tools.mcp.types import MCPToolInfo
from lifeops.tools.base import ToolResult
from lifeops.tools.registry import ToolRegistry
from lifeops.utils.logging import get_logger
from lifeops.utils.logging import setup_logger
from lifeops.web.title_summary import fallback_conversation_title, summarize_conversation_title

logger = get_logger(__name__)

_RAG_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg"}


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


class MemorySearchRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int | None = Field(default=None, ge=1)


class MemoryForgetRequest(BaseModel):
    dry_run: bool = True
    preference_confidence_below: float = Field(default=0.2, ge=0, le=1)
    relation_strength_below: float = Field(default=0.2, ge=0, le=1)


def create_app(config: AppConfig | None = None) -> FastAPI:
    app_config = config or AppConfig()
    app = FastAPI(title="LifeOps Web API", version="0.1.0", lifespan=_lifespan(app_config))
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^http://(localhost|127\.0\.0\.1):\d+$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.config = app_config
    app.state.history_store = ConversationHistoryStoreSQLite(app_config.db_path)
    app.state.web_agents = {}
    app.state.services = _create_agent_services(app_config)
    app.state.memory_service = MemoryService(
        app.state.history_store,
        app.state.services.llm,
        app_config.memory,
        embedding_provider=_create_memory_embedding_provider(app_config),
    )
    app.state.tool_registry = app.state.services.base_tool_registry
    app.state.mcp_manager = app.state.services.mcp_manager
    app.state.services_started = False
    app.state.mcp_started = False

    @app.get("/api/conversations")
    async def list_conversations(
        query: str | None = None,
        limit: int | None = Query(None, ge=1),
        offset: int | None = Query(None, ge=0),
    ) -> dict[str, Any]:
        try:
            result = app.state.history_store.list_conversations(query, limit=limit, offset=offset)
        except Exception:
            logger.exception("列出会话失败")
            raise HTTPException(status_code=500, detail="列出会话时发生内部错误")
        if isinstance(result, list):
            return {"conversations": result}
        return {
            "conversations": result["items"],
            "total": result["total"],
            "limit": result["limit"],
            "offset": result["offset"],
        }

    @app.get("/api/conversations/{conversation_id}")
    async def get_conversation(
        conversation_id: str,
        limit: int | None = Query(None, ge=1),
        offset: int | None = Query(None, ge=0),
    ) -> dict[str, Any]:
        try:
            all_messages = app.state.history_store.get_messages(
                conversation_id, limit=limit, offset=offset
            )
        except Exception:
            logger.exception("获取会话详情失败")
            raise HTTPException(status_code=500, detail="获取会话详情时发生内部错误")

        if isinstance(all_messages, list):
            messages = [m for m in all_messages if not _is_intermediate_message(m)]
            intermediate_messages = [m for m in all_messages if _is_intermediate_message(m)]
            return {
                "conversation_id": conversation_id,
                "messages": messages,
                "intermediate_messages": intermediate_messages,
            }

        items = all_messages["items"]
        messages = [m for m in items if not _is_intermediate_message(m)]
        intermediate_messages = [m for m in items if _is_intermediate_message(m)]
        return {
            "conversation_id": conversation_id,
            "messages": messages,
            "intermediate_messages": intermediate_messages,
            "total": all_messages["total"],
            "limit": all_messages["limit"],
            "offset": all_messages["offset"],
        }

    @app.delete("/api/conversations/{conversation_id}")
    async def delete_conversation(conversation_id: str) -> dict[str, Any]:
        try:
            deleted_count = app.state.history_store.delete_conversation(conversation_id)
        except Exception:
            logger.exception("删除会话失败")
            raise HTTPException(status_code=500, detail="删除会话时发生内部错误")
        app.state.web_agents.pop(conversation_id, None)
        return {"conversation_id": conversation_id, "deleted_count": deleted_count}

    @app.get("/api/search/messages")
    async def search_messages(
        q: str = Query(..., min_length=1),
        limit: int = Query(20, ge=1),
        offset: int = Query(0, ge=0),
    ) -> dict[str, Any]:
        try:
            return app.state.history_store.search_messages(q, limit, offset)
        except Exception:
            logger.exception("搜索消息失败")
            raise HTTPException(status_code=500, detail="搜索消息时发生内部错误")

    @app.get("/api/memory/stats")
    async def memory_stats() -> dict[str, Any]:
        try:
            return app.state.memory_service.stats()
        except Exception:
            logger.exception("读取记忆统计失败")
            raise HTTPException(status_code=500, detail="读取记忆统计时发生内部错误")

    @app.get("/api/memory/user-profile")
    async def memory_user_profile() -> dict[str, Any]:
        try:
            return app.state.memory_service.user_profile()
        except Exception:
            logger.exception("读取用户画像失败")
            raise HTTPException(status_code=500, detail="读取用户画像时发生内部错误")

    @app.get("/api/memory/knowledge-graph")
    async def memory_knowledge_graph() -> dict[str, Any]:
        try:
            return app.state.memory_service.knowledge_graph()
        except Exception:
            logger.exception("读取知识图谱失败")
            raise HTTPException(status_code=500, detail="读取知识图谱时发生内部错误")

    @app.get("/api/memory/summaries")
    async def memory_summaries(
        limit: int | None = Query(None, ge=1),
        offset: int = Query(0, ge=0),
    ) -> dict[str, Any]:
        try:
            return {
                "summaries": app.state.memory_service.summaries(
                    limit=limit,
                    offset=offset,
                )
            }
        except Exception:
            logger.exception("读取记忆摘要失败")
            raise HTTPException(status_code=500, detail="读取记忆摘要时发生内部错误")

    @app.get("/api/memory/compression-events")
    async def memory_compression_events(
        limit: int | None = Query(None, ge=1),
        offset: int = Query(0, ge=0),
    ) -> dict[str, Any]:
        try:
            return {
                "events": app.state.memory_service.compression_events(
                    limit=limit,
                    offset=offset,
                )
            }
        except Exception:
            logger.exception("读取压缩事件失败")
            raise HTTPException(status_code=500, detail="读取压缩事件时发生内部错误")

    @app.get("/api/memory/skill-usage")
    async def memory_skill_usage() -> dict[str, Any]:
        try:
            return {"skills": app.state.memory_service.skill_usage()}
        except Exception:
            logger.exception("读取 Skill 使用统计失败")
            raise HTTPException(status_code=500, detail="读取 Skill 使用统计时发生内部错误")

    @app.get("/api/memory/tool-stats")
    async def memory_tool_stats() -> dict[str, Any]:
        try:
            return {"tools": app.state.memory_service.tool_stats()}
        except Exception:
            logger.exception("读取工具统计失败")
            raise HTTPException(status_code=500, detail="读取工具统计时发生内部错误")

    @app.post("/api/memory/search")
    async def memory_search(request: MemorySearchRequest) -> dict[str, Any]:
        try:
            return app.state.memory_service.search(request.query, top_k=request.top_k)
        except Exception:
            logger.exception("搜索长期记忆失败")
            raise HTTPException(status_code=500, detail="搜索长期记忆时发生内部错误")

    @app.delete("/api/memory/preferences/{preference_id}")
    async def memory_delete_preference(preference_id: str) -> dict[str, Any]:
        try:
            return {"deleted": app.state.memory_service.delete_preference(preference_id)}
        except Exception:
            logger.exception("删除用户偏好失败")
            raise HTTPException(status_code=500, detail="删除用户偏好时发生内部错误")

    @app.delete("/api/memory/entities/{entity_id}")
    async def memory_delete_entity(entity_id: str) -> dict[str, Any]:
        try:
            return {"deleted": app.state.memory_service.delete_entity(entity_id)}
        except Exception:
            logger.exception("删除知识图谱实体失败")
            raise HTTPException(status_code=500, detail="删除知识图谱实体时发生内部错误")

    @app.post("/api/memory/maintenance/forget")
    async def memory_forget(request: MemoryForgetRequest) -> dict[str, Any]:
        try:
            return app.state.memory_service.forget(
                dry_run=request.dry_run,
                preference_confidence_below=request.preference_confidence_below,
                relation_strength_below=request.relation_strength_below,
            )
        except Exception:
            logger.exception("执行记忆清理失败")
            raise HTTPException(status_code=500, detail="执行记忆清理时发生内部错误")

    @app.post("/api/chat")
    async def chat(
        request: ChatRequest,
        resume_from: int | None = Query(None),
    ) -> StreamingResponse:
        if not app.state.config.llm.api_key:
            raise HTTPException(
                status_code=400,
                detail="LLM_API_KEY 未设置。请在 .env 或环境变量中配置后再启动 Web API。",
            )

        is_new_conversation = request.conversation_id is None
        conversation_id = request.conversation_id or _new_web_conversation_id()
        await _ensure_services_initialized(app, include_mcp=False)
        agent = _get_or_create_web_agent(app, conversation_id)
        title_task = None
        if is_new_conversation:
            logger.info(f"Web 新会话进入标题生成: conversation_id={conversation_id}")
            title_task = asyncio.create_task(
                summarize_conversation_title(agent.llm, request.message)
            )

        return StreamingResponse(
            _generate_sse_messages(
                agent=agent,
                user_message=request.message,
                conversation_id=conversation_id,
                is_new_conversation=is_new_conversation,
                title_task=title_task,
                history_store=app.state.history_store,
                first_user_message=request.message,
                memory_service=app.state.memory_service,
                resume_from=resume_from,
            ),
            media_type="text/event-stream",
        )

    @app.get("/api/skills")
    async def list_skills() -> dict[str, Any]:
        await _ensure_services_initialized(app, include_mcp=False)
        manager = _skill_manager_from_catalog(app.state.config, app.state.services.skill_catalog)
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
        await _ensure_services_initialized(app, include_mcp=False)
        existing_manager = _skill_manager_from_catalog(
            app.state.config, app.state.services.skill_catalog
        )
        if request.name in existing_manager.skills:
            raise HTTPException(status_code=409, detail=f"Skill '{request.name}' 已存在。")

        metadata = _parse_metadata_fragment(request.metadata)
        skill_file = _write_project_skill(app.state.config, request, metadata)
        _refresh_global_skill_catalog(app)
        return {"name": request.name, "path": str(skill_file)}

    @app.get("/api/rag/assets/{asset_path:path}")
    async def get_rag_asset(asset_path: str) -> FileResponse:
        asset_file = _resolve_rag_asset(app.state.config, asset_path)
        return FileResponse(asset_file)

    @app.get("/api/tools")
    async def list_tools() -> dict[str, Any]:
        await _ensure_services_initialized(app)
        registry: ToolRegistry = app.state.services.base_tool_registry
        mcp_servers = await _describe_mcp_servers(app.state.services.mcp_manager)
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


def _lifespan(config: AppConfig):
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await _ensure_services_initialized(app)
        try:
            yield
        finally:
            await app.state.services.mcp_manager.disconnect_all()

    return lifespan


def _create_agent_services(config: AppConfig) -> AgentServices:
    from lifeops.agent import LLMClient as AgentLLMClient

    base_tool_registry = ToolRegistry()
    register_all_builtin_tools(base_tool_registry, config)
    mcp_manager = MCPManager()
    if config.mcp.enabled and config.mcp.servers.strip():
        mcp_manager.load_from_config(config.mcp.servers)
    llm = AgentLLMClient(
        api_key=config.llm.api_key,
        model=config.llm.model,
        api_base=config.llm.api_base,
        max_tokens=config.llm.max_tokens,
        temperature=config.llm.temperature,
        timeout=config.llm.timeout,
    )
    return AgentServices(
        llm=llm,
        base_tool_registry=base_tool_registry,
        mcp_manager=mcp_manager,
    )


def _create_memory_embedding_provider(config: AppConfig) -> Any | None:
    try:
        return SentenceTransformerEmbeddingProvider(
            config.rag.embedding_model,
            cache_folder=config.rag.model_cache_path,
        )
    except Exception:
        logger.warning("长期记忆 embedding provider 初始化失败，将仅使用 BM25", exc_info=True)
        return None


async def _ensure_services_initialized(app: FastAPI, *, include_mcp: bool = True) -> None:
    if getattr(app.state, "services_started", False):
        if include_mcp:
            await _ensure_mcp_initialized(app)
        return

    services: AgentServices = app.state.services
    config: AppConfig = app.state.config

    if not hasattr(app.state, "services_start_lock"):
        app.state.services_start_lock = asyncio.Lock()

    async with app.state.services_start_lock:
        if getattr(app.state, "services_started", False):
            if include_mcp:
                await _ensure_mcp_initialized(app)
            return

        jsonl_path = object.__getattribute__(config, "history_path")
        try:
            migration_result = auto_migrate(jsonl_path, config.db_path)
            if migration_result is not None:
                logger.info(
                    "Web 启动 JSONL 迁移完成: 成功 %d 条, 失败 %d 条",
                    migration_result["success"],
                    migration_result["failed"],
                )
        except Exception as exc:
            logger.warning("Web 启动 JSONL 迁移失败，继续启动: %s", exc)

        if config.rag.enabled:
            try:
                summary = RAGIndexer(config.rag).sync()
                logger.info("Web 启动 RAG 索引同步完成: %s", summary)
            except Exception as exc:
                logger.warning("Web 启动 RAG 索引同步失败，继续启动: %s", exc)

            try:
                from lifeops.rag.retriever import RAGRetriever

                services.rag_retriever = RAGRetriever(config.rag)
                services.rag_retriever.warm_up()
                logger.info("Web 启动 RAG 模型预热完成")
            except Exception as exc:
                logger.warning("Web 启动 RAG 模型预热失败，继续启动: %s", exc)

        if config.skills.enabled:
            manager = _discover_skill_manager(config)
            services.skill_catalog = manager.catalog

        app.state.services_started = True
        if include_mcp:
            await _ensure_mcp_initialized(app)


async def _ensure_mcp_initialized(app: FastAPI) -> None:
    if getattr(app.state, "mcp_started", False):
        return
    services: AgentServices = app.state.services
    config: AppConfig = app.state.config
    if _should_skip_pytest_env_mcp(config):
        app.state.mcp_started = True
        return
    if config.mcp.enabled and services.mcp_manager.list_servers():
        try:
            await asyncio.wait_for(
                services.mcp_manager.connect_and_register_all(services.base_tool_registry),
                timeout=10,
            )
        except TimeoutError:
            logger.warning("Web 启动 MCP 连接超时，继续启动")
    app.state.mcp_started = True


def _should_skip_pytest_env_mcp(config: AppConfig) -> bool:
    if "PYTEST_CURRENT_TEST" not in os.environ:
        return False
    servers = config.mcp.servers
    return any(marker in servers for marker in ('"command":"docker"', '"command":"uvx"', "workspace-mcp"))


def _get_or_create_web_agent(app: FastAPI, conversation_id: str) -> Agent:
    agents: dict[str, Agent] = app.state.web_agents
    if conversation_id in agents:
        return agents[conversation_id]

    agent = Agent(
        app.state.config,
        history_store=app.state.history_store,
        source="web",
        conversation_id=conversation_id,
        services=app.state.services,
        memory_service=app.state.memory_service,
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
    history_store: ConversationHistoryStoreSQLite,
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


async def _generate_sse_messages(
    *,
    agent: Agent,
    user_message: str,
    conversation_id: str,
    is_new_conversation: bool,
    title_task: asyncio.Task | None,
    history_store: ConversationHistoryStoreSQLite,
    first_user_message: str,
    memory_service: MemoryService | None = None,
    resume_from: int | None = None,
):
    queue: asyncio.Queue[str] = asyncio.Queue()
    next_event_id = 0
    previous_on_tool_call = getattr(agent, "on_tool_call", None)
    previous_on_tool_result = getattr(agent, "on_tool_result", None)
    previous_on_token = getattr(agent, "on_token", None)

    def make_sse(event_type: str, data: Any, *, always_send: bool = False) -> str | None:
        nonlocal next_event_id
        event_id = next_event_id
        next_event_id += 1
        if not always_send and resume_from is not None and event_id <= resume_from:
            return None
        return _sse_line(event_type, data, event_id=event_id)

    async def on_tool_call(tool_name: str, params: dict[str, Any]) -> None:
        line = make_sse(
            "tool_call",
            {
                "name": tool_name,
                "args": params,
                "tool_name": tool_name,
                "params": params,
            },
        )
        if line is not None:
            await queue.put(line)
        if previous_on_tool_call is not None:
            await previous_on_tool_call(tool_name, params)

    async def on_tool_result(tool_name: str, result: ToolResult) -> None:
        payload = {
            "tool_name": tool_name,
            "success": result.success,
            "result": result.output,
            "output": result.output,
            "error": result.error,
            "metadata": result.metadata,
        }
        line = make_sse("tool_result", payload)
        if line is not None:
            await queue.put(line)
        if not result.success:
            line = make_sse(
                "tool_error",
                {"tool_name": tool_name, "error": result.error or "工具执行失败"},
            )
            if line is not None:
                await queue.put(line)
        if previous_on_tool_result is not None:
            await previous_on_tool_result(tool_name, result)

    async def on_token(token: str) -> None:
        line = make_sse("token", token)
        if line is not None:
            await queue.put(line)
        if previous_on_token is not None:
            await previous_on_token(token)

    agent.on_tool_call = on_tool_call
    agent.on_tool_result = on_tool_result
    agent.on_token = on_token
    run_task = asyncio.create_task(agent.run(user_message))
    title: str | None = None

    try:
        while not run_task.done():
            try:
                yield await asyncio.wait_for(queue.get(), timeout=0.05)
            except TimeoutError:
                continue

        while not queue.empty():
            yield await queue.get()

        try:
            await run_task
        except Exception as exc:
            line = make_sse("error", str(exc))
            if line is not None:
                yield line

        if is_new_conversation:
            if title_task is not None:
                try:
                    title_result = await title_task
                except Exception as exc:
                    title_result = exc
                title = _resolve_title_result(first_user_message, title_result, conversation_id)
            else:
                title = fallback_conversation_title(first_user_message)
            history_store.append_conversation_title(conversation_id, "web", title)
        else:
            title = await _backfill_conversation_title_if_missing(
                history_store,
                conversation_id,
                agent.llm,
            )

        if memory_service is not None:
            try:
                await memory_service.finalize_conversation(conversation_id)
            except Exception:
                logger.exception("Web SSE 结束时更新长期记忆失败")

        yield make_sse(
            "done",
            {"conversation_id": conversation_id, "title": title},
            always_send=True,
        )
    finally:
        agent.on_tool_call = previous_on_tool_call
        agent.on_tool_result = previous_on_tool_result
        agent.on_token = previous_on_token


def _sse_line(event_type: str, data: Any, event_id: int | None = None) -> str:
    payload = {
        "id": uuid4().hex if event_id is None else event_id,
        "type": event_type,
        "data": data,
    }
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


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


def _skill_manager_from_catalog(config: AppConfig, catalog: Any | None) -> SkillManager:
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
    if catalog is None:
        manager.discover()
    else:
        manager.catalog = catalog
        manager.inject_catalog()
    return manager


def _refresh_global_skill_catalog(app: FastAPI) -> None:
    if not app.state.config.skills.enabled:
        return
    manager = _discover_skill_manager(app.state.config)
    app.state.services.skill_catalog = manager.catalog


def _resolve_rag_asset(config: AppConfig, asset_path: str) -> Path:
    if _is_unsafe_rag_asset_path(asset_path):
        raise HTTPException(status_code=403, detail="RAG 资源路径无效。")

    relative_path = PurePosixPath(asset_path)
    if relative_path.suffix.lower() not in _RAG_IMAGE_EXTENSIONS:
        raise HTTPException(status_code=415, detail="仅支持读取知识库图片资源。")

    for root in _rag_data_roots(config):
        candidate = (root / Path(*relative_path.parts)).resolve()
        if not candidate.is_relative_to(root):
            continue
        if candidate.is_file():
            return candidate

    raise HTTPException(status_code=404, detail="RAG 图片资源不存在。")


def _is_unsafe_rag_asset_path(asset_path: str) -> bool:
    if not asset_path or "\x00" in asset_path or "\\" in asset_path or asset_path.startswith("/"):
        return True
    parts = PurePosixPath(asset_path).parts
    return any(part in {"", ".", ".."} for part in parts)


def _rag_data_roots(config: AppConfig) -> list[Path]:
    roots: list[Path] = []
    for raw_root in config.rag.data_dirs_list:
        root = Path(raw_root).expanduser()
        if not root.is_absolute():
            root = PROJECT_ROOT / root
        roots.append(root.resolve())
    return roots


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


async def _describe_mcp_servers(manager: MCPManager) -> list[dict[str, Any]]:
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
