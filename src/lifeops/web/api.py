from __future__ import annotations

import asyncio
import inspect
import json
import os
import re
import shutil
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

import yaml
from fastapi import File, FastAPI, Form, HTTPException, Query, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator

from lifeops.agent import APPROVAL_DECISIONS, Agent, AgentServices, ApprovalRequest
from lifeops.core.config import PROJECT_ROOT, AppConfig, clear_proxy_env
from lifeops.core.context_manager import ContextManager
from lifeops.llm.types import Message, MessageRole
from lifeops.memory import MemoryService
from lifeops.rag.embeddings import SentenceTransformerEmbeddingProvider
from lifeops.rag.importer import extract_zip_archive, preview_markdown
from lifeops.rag.indexer import RAGIndexer
from lifeops.rag.types import RAGSourceConfig
from lifeops.runtime.policy import ToolPolicyEngine
from lifeops.runtime.policy_file import PolicyFileStore
from lifeops.runtime.policy_rules import default_policy_summary
from lifeops.runtime.store import RuntimeStore
from lifeops.runtime.types import RunStatus, TraceEventType, TraceRecorder
from lifeops.storage import ConversationHistoryStoreSQLite, auto_migrate
from lifeops.skills.manager import SkillManager
from lifeops.tools.builtin import register_all_builtin_tools
from lifeops.tools.mcp.manager import MCPManager
from lifeops.tools.mcp.types import MCPToolInfo
from lifeops.tools.base import ToolResult
from lifeops.tools.registry import ToolRegistry
from lifeops.tools.schema import parameters_schema_from_model
from lifeops.utils.logging import get_logger
from lifeops.utils.logging import setup_logger
from lifeops.web.title_summary import fallback_conversation_title, summarize_conversation_title

logger = get_logger(__name__)

_RAG_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg"}
_RAG_IMPORT_PENDING = ".lifeops-import-pending.json"
_RAG_IMPORT_COMPLETE = ".lifeops-import-complete.json"


class _SkillYamlDumper(yaml.SafeDumper):
    pass


def _represent_skill_string(dumper: yaml.SafeDumper, value: str) -> Any:
    style = "|" if "\n" in value else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


_SkillYamlDumper.add_representer(str, _represent_skill_string)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    conversation_id: str | None = None


class ApprovalDecisionRequest(BaseModel):
    decision: str = Field(min_length=1)


class ChatResponse(BaseModel):
    conversation_id: str
    reply: str
    title: str | None = None


class CreateSkillRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    description: str = Field(min_length=1, max_length=1024)
    license: str | None = None
    compatibility: str | None = Field(default=None, max_length=500)
    allowed_tools: list[str] = Field(default_factory=list)
    metadata: str = ""
    content: str = Field(min_length=1)

    model_config = {"str_strip_whitespace": True}


class CreateRAGSourceRequest(BaseModel):
    source_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=1000)
    call_when: str = Field(min_length=1, max_length=1000)
    enabled: bool = True

    model_config = {"str_strip_whitespace": True}

    @field_validator("name", "description", "call_when")
    @classmethod
    def validate_single_line_text(cls, value: str) -> str:
        return _validate_rag_source_text(value)


class UpdateRAGSourceRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, min_length=1, max_length=1000)
    call_when: str | None = Field(default=None, min_length=1, max_length=1000)
    enabled: bool | None = None

    model_config = {"str_strip_whitespace": True}

    @field_validator("name", "description", "call_when")
    @classmethod
    def validate_single_line_text(cls, value: str | None) -> str | None:
        return _validate_rag_source_text(value) if value is not None else None


class RAGImportPreviewRequest(BaseModel):
    strategy: str = Field(pattern=r"^(fixed|heading)$")
    chunk_size: int = Field(default=900, ge=150, le=900)


class RAGImportStartRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=1000)
    call_when: str = Field(min_length=1, max_length=1000)
    strategy: str = Field(pattern=r"^(fixed|heading)$")
    chunk_size: int = Field(default=900, ge=150, le=900)
    enabled: bool = True

    model_config = {"str_strip_whitespace": True}

    @field_validator("name", "description", "call_when")
    @classmethod
    def validate_single_line_text(cls, value: str) -> str:
        return _validate_rag_source_text(value)


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
    app.state.runtime_store = RuntimeStore(
        app.state.history_store,
        trace_max_payload_chars=app_config.runtime.trace_max_payload_chars,
    )
    app.state.tool_policy_engine = ToolPolicyEngine(
        app_config.tool_policy,
        policy_file=PolicyFileStore(app_config.tool_policy.path),
    )
    app.state.web_agents = {}
    app.state.pending_approvals: dict[str, tuple[asyncio.Future, ApprovalRequest]] = {}
    app.state.services = _create_agent_services(app_config)
    app.state.memory_service = MemoryService(
        app.state.history_store,
        app.state.services.llm,
        app_config.memory,
        embedding_provider=_create_memory_embedding_provider(app_config),
    )
    app.state.tool_registry = app.state.services.base_tool_registry
    app.state.mcp_manager = app.state.services.mcp_manager
    app.state.background_tasks = set()
    app.state.rag_imports = {}
    app.state.rag_import_lock = asyncio.Lock()
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
        latest: bool = False,
        before_id: int | None = Query(None, ge=1),
    ) -> dict[str, Any]:
        cursor_mode = latest or before_id is not None
        if cursor_mode and offset is not None:
            raise HTTPException(
                status_code=422,
                detail="before_id/latest 不能与 offset 同时使用",
            )
        if cursor_mode and limit is not None and limit > 200:
            raise HTTPException(status_code=422, detail="游标分页 limit 不能超过 200")
        try:
            if cursor_mode:
                all_messages = app.state.history_store.get_messages_cursor(
                    conversation_id,
                    limit=limit or 50,
                    before_id=before_id,
                )
            else:
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
                "messages": _strip_private_message_fields(messages),
                "intermediate_messages": _strip_private_message_fields(intermediate_messages),
            }

        items = all_messages["items"]
        messages = [m for m in items if not _is_intermediate_message(m)]
        intermediate_messages = [m for m in items if _is_intermediate_message(m)]
        return {
            "conversation_id": conversation_id,
            "messages": _strip_private_message_fields(messages),
            "intermediate_messages": _strip_private_message_fields(intermediate_messages),
            "total": all_messages["total"],
            "limit": all_messages["limit"],
            "offset": all_messages["offset"],
            "has_more": all_messages.get("has_more", False),
            "next_before_id": all_messages.get("next_before_id"),
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
            return _strip_private_message_fields(
                app.state.history_store.search_messages(q, limit, offset)
            )
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
        run_id = uuid4().hex
        if app.state.config.runtime.enabled:
            app.state.runtime_store.create_run(
                conversation_id=conversation_id,
                source="web",
                user_input=request.message,
                run_id=run_id,
            )
        agent = _get_or_create_web_agent(app, conversation_id, run_id=run_id)
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
                runtime_store=app.state.runtime_store,
                run_id=run_id,
                resume_from=resume_from,
                background_tasks=app.state.background_tasks,
                pending_approvals=app.state.pending_approvals,
            ),
            media_type="text/event-stream",
        )

    @app.post("/api/approvals/{request_id}")
    async def resolve_approval(request_id: str, request: ApprovalDecisionRequest) -> dict[str, Any]:
        pending = app.state.pending_approvals.get(request_id)
        if pending is None:
            raise HTTPException(status_code=404, detail="审批请求不存在或已结束")
        future, approval_request = pending
        decision = request.decision
        if decision not in APPROVAL_DECISIONS:
            raise HTTPException(status_code=422, detail=f"无效的审批决策: {decision}")
        if not future.done():
            future.set_result(decision)
        return {
            "request_id": request_id,
            "decision": decision,
            "tool_name": approval_request.tool_name,
        }

    @app.get("/api/runs/{run_id}")
    async def get_run(run_id: str) -> dict[str, Any]:
        run = app.state.runtime_store.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run 不存在")
        return {"run": run, "events": app.state.runtime_store.list_run_events(run_id)}

    @app.get("/api/conversations/{conversation_id}/runs")
    async def list_conversation_runs(conversation_id: str) -> dict[str, Any]:
        return {"runs": app.state.runtime_store.list_conversation_runs(conversation_id)}

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
                "license": skill.license,
                "compatibility": skill.compatibility,
                "metadata": skill.metadata,
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

    @app.get("/api/rag/sources")
    async def list_rag_sources() -> dict[str, Any]:
        return {"sources": app.state.history_store.list_rag_sources()}

    @app.post("/api/rag/sources", status_code=status.HTTP_201_CREATED)
    async def create_rag_source(request: CreateRAGSourceRequest) -> dict[str, Any]:
        source = request.model_dump()
        source["path_prefix"] = _normalize_rag_source_path(
            app.state.config, request.source_id
        )
        try:
            created = app.state.history_store.create_rag_source(source)
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="数据源标识或对应目录已存在。") from exc
        return {"source": created, "restart_required": True}

    @app.patch("/api/rag/sources/{source_id}")
    async def update_rag_source(
        source_id: str, request: UpdateRAGSourceRequest
    ) -> dict[str, Any]:
        source = app.state.history_store.get_rag_source(source_id)
        if source is None:
            raise HTTPException(status_code=404, detail="本地知识库不存在。")
        updated = app.state.history_store.update_rag_source(
            source_id, request.model_dump(exclude_unset=True)
        )
        return {"source": updated, "restart_required": True}

    @app.delete("/api/rag/sources/{source_id}")
    async def delete_rag_source(source_id: str) -> dict[str, Any]:
        if not app.state.history_store.delete_rag_source(source_id):
            raise HTTPException(status_code=404, detail="本地知识库不存在。")
        return {"deleted": True, "restart_required": True}

    @app.get("/api/rag/imports/conflict")
    async def rag_import_conflict(source_id: str = Query(...)) -> dict[str, Any]:
        source_id = _validate_rag_source_id(source_id)
        return {"source_id": source_id, "conflict": _rag_import_conflicts(app, source_id)}

    @app.post("/api/rag/imports", status_code=status.HTTP_201_CREATED)
    async def upload_rag_import(
        source_id: str = Form(...),
        overwrite: bool = Form(False),
        archive: UploadFile = File(...),
    ) -> dict[str, Any]:
        source_id = _validate_rag_source_id(source_id)
        if not archive.filename or not archive.filename.lower().endswith(".zip"):
            raise HTTPException(status_code=415, detail="暂时只支持 ZIP 压缩包。")
        if _rag_import_conflicts(app, source_id) and not overwrite:
            raise HTTPException(
                status_code=409,
                detail="知识库已存在，继续上传会覆盖已有知识库，请确认后重试。",
            )

        root = _rag_import_root(app, source_id)
        root.mkdir(parents=True, exist_ok=True)
        import_id = uuid4().hex
        import_dir = root / ".imports" / import_id
        import_dir.mkdir(parents=True, exist_ok=False)
        archive_path = import_dir / "archive.zip"
        extract_dir = import_dir / _archive_stem(archive.filename)
        try:
            await _save_upload(archive, archive_path)
            manifest = extract_zip_archive(archive_path, extract_dir)
        except HTTPException:
            shutil.rmtree(import_dir, ignore_errors=True)
            raise
        except ValueError as exc:
            shutil.rmtree(import_dir, ignore_errors=True)
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except OSError as exc:
            shutil.rmtree(import_dir, ignore_errors=True)
            raise HTTPException(status_code=500, detail="上传文件暂存失败。") from exc
        finally:
            await archive.close()

        record = {
            "import_id": import_id,
            "source_id": source_id,
            "extract_dir": str(extract_dir),
            "import_dir": str(import_dir),
            "root": str(root),
            "existing_path": str(_rag_existing_path(app, source_id, root)),
            "overwrite": bool(overwrite),
            "status": "uploaded",
            "markdown_files": manifest["markdown_files"],
            "files": manifest["files"],
        }
        app.state.rag_imports[import_id] = record
        return {
            "import_id": import_id,
            "source_id": source_id,
            "tree": _build_import_tree(extract_dir),
            "markdown_files": manifest["markdown_files"],
            "ignored_files": manifest["ignored_files"],
        }

    @app.post("/api/rag/imports/{import_id}/preview")
    async def preview_rag_import(
        import_id: str, request: RAGImportPreviewRequest
    ) -> dict[str, Any]:
        record = _get_rag_import(app, import_id)
        if record["status"] not in {"uploaded", "previewed"}:
            raise HTTPException(status_code=409, detail="当前导入状态不支持预览。")
        relative_path = record["markdown_files"][0]
        preview = preview_markdown(
            Path(record["extract_dir"]) / Path(*PurePosixPath(relative_path).parts),
            strategy=request.strategy,
            chunk_size=request.chunk_size,
        )
        preview["path"] = relative_path
        app.state.rag_imports[import_id] = {
            **record,
            "status": "previewed",
            "strategy": request.strategy,
            "chunk_size": request.chunk_size,
        }
        return preview

    @app.post("/api/rag/imports/{import_id}/start", status_code=status.HTTP_202_ACCEPTED)
    async def start_rag_import(
        import_id: str, request: RAGImportStartRequest
    ) -> dict[str, Any]:
        record = _get_rag_import(app, import_id)
        if record["status"] not in {"uploaded", "previewed"}:
            raise HTTPException(status_code=409, detail="当前导入任务不能开始处理。")
        if any(item.get("status") == "processing" for item in app.state.rag_imports.values()):
            raise HTTPException(status_code=409, detail="已有知识库正在处理中，请稍后重试。")
        if record["status"] == "uploaded":
            raise HTTPException(status_code=409, detail="请先完成切片预览。")

        task_record = {
            **record,
            **request.model_dump(),
            "status": "processing",
        }
        app.state.rag_imports[import_id] = task_record
        _schedule_background_task(
            app.state.background_tasks,
            _process_rag_import(app, task_record),
            name=f"rag-import-{import_id}",
        )
        return {"import_id": import_id, "status": "processing"}

    @app.get("/api/rag/imports/{import_id}")
    async def get_rag_import(import_id: str) -> dict[str, Any]:
        record = _get_rag_import(app, import_id)
        return {
            key: record[key]
            for key in (
                "import_id", "source_id", "status", "strategy", "chunk_size", "summary", "error"
            )
            if key in record
        }

    @app.delete("/api/rag/imports/{import_id}")
    async def delete_rag_import(import_id: str) -> dict[str, Any]:
        record = _get_rag_import(app, import_id)
        if record["status"] == "processing":
            raise HTTPException(status_code=409, detail="知识库正在处理中，不能删除。")
        shutil.rmtree(record["import_dir"], ignore_errors=True)
        app.state.rag_imports.pop(import_id, None)
        return {"deleted": True}

    @app.get("/api/rag/assets/{asset_path:path}")
    async def get_rag_asset(asset_path: str) -> FileResponse:
        asset_file = _resolve_rag_asset(app.state.config, asset_path)
        return FileResponse(asset_file)

    @app.get("/api/tools/policy")
    async def tools_policy() -> dict[str, Any]:
        return default_policy_summary(app.state.config.tool_policy.mode)

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
                "parameters": parameters_schema_from_model(tool.parameters_model),
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
    if config.mcp.enabled:
        if config.mcp.servers.strip():
            mcp_manager.load_from_config(config.mcp.servers)
        if config.mcp.presets.strip() and "PYTEST_CURRENT_TEST" not in os.environ:
            mcp_manager.load_presets(config.mcp.presets)
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

        try:
            _recover_rag_imports(app)
        except Exception as exc:
            logger.warning("Web 启动清理本地知识库导入残留失败，继续启动: %s", exc)

        source_configs = _rag_source_configs(app.state.history_store)
        if config.rag.enabled:
            try:
                summary = RAGIndexer(config.rag, source_configs=source_configs).sync()
                logger.info("Web 启动 RAG 索引同步完成: %s", summary)
            except Exception as exc:
                logger.warning("Web 启动 RAG 索引同步失败，继续启动: %s", exc)

            try:
                from lifeops.rag.retriever import RAGRetriever
                from lifeops.rag.router import build_default_rag_router

                backend = RAGRetriever(config.rag)
                backend.warm_up()
                enabled_source_configs = _rag_source_configs(
                    app.state.history_store, enabled_only=True
                )
                services.rag_router = build_default_rag_router(
                    config.rag,
                    backend,
                    sources=enabled_source_configs,
                )
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
    return bool(config.mcp.presets.strip())


def _get_or_create_web_agent(
    app: FastAPI, conversation_id: str, run_id: str | None = None
) -> Agent:
    agents: dict[str, Agent] = app.state.web_agents
    if conversation_id in agents:
        agent = agents[conversation_id]
        agent.run_id = run_id
        agent.trace_recorder = TraceRecorder(app.state.runtime_store) if run_id else None
        agent.tool_policy_engine = app.state.tool_policy_engine
        agent.messages = _hydrate_messages(
            app.state.history_store.get_messages(conversation_id)
        )
        return agent

    agent = Agent(
        app.state.config,
        history_store=app.state.history_store,
        source="web",
        conversation_id=conversation_id,
        services=app.state.services,
        memory_service=app.state.memory_service,
        run_id=run_id,
        trace_recorder=TraceRecorder(app.state.runtime_store) if run_id else None,
        tool_policy_engine=app.state.tool_policy_engine,
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
                reasoning_content=record.get("reasoning_content"),
            )
        )
    return messages


def _strip_private_message_fields(value: Any) -> Any:
    if isinstance(value, list):
        return [_strip_private_message_fields(item) for item in value]
    if isinstance(value, dict):
        return {
            key: _strip_private_message_fields(item)
            for key, item in value.items()
            if key != "reasoning_content"
        }
    return value


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


def _schedule_background_task(
    background_tasks: set[asyncio.Task],
    coro: Any,
    *,
    name: str,
) -> asyncio.Task:
    task = asyncio.create_task(coro, name=name)
    background_tasks.add(task)

    def discard_and_log(completed_task: asyncio.Task) -> None:
        background_tasks.discard(completed_task)
        try:
            completed_task.result()
        except asyncio.CancelledError:
            logger.warning("Web 后台任务已取消: %s", name)
        except Exception:
            logger.exception("Web 后台任务失败: %s", name)

    task.add_done_callback(discard_and_log)
    return task


async def _persist_generated_title(
    *,
    title_task: asyncio.Task | None,
    history_store: ConversationHistoryStoreSQLite,
    conversation_id: str,
    first_user_message: str,
) -> None:
    if title_task is None:
        title = fallback_conversation_title(first_user_message)
    else:
        try:
            title_result = await title_task
        except Exception as exc:
            title_result = exc
        title = _resolve_title_result(first_user_message, title_result, conversation_id)
    history_store.append_conversation_title(conversation_id, "web", title)


async def _finalize_memory_in_background(
    *,
    memory_service: MemoryService,
    conversation_id: str,
    run_id: str | None,
    trace_recorder: TraceRecorder | None,
) -> None:
    finalize = memory_service.finalize_conversation
    if _call_accepts_keyword(finalize, "run_id"):
        await finalize(
            conversation_id,
            run_id=run_id,
            trace_recorder=trace_recorder,
        )
    else:
        await finalize(conversation_id)


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
    runtime_store: RuntimeStore | None = None,
    run_id: str | None = None,
    resume_from: int | None = None,
    background_tasks: set[asyncio.Task] | None = None,
    pending_approvals: dict[str, tuple[asyncio.Future, ApprovalRequest]] | None = None,
):
    queue: asyncio.Queue[str] = asyncio.Queue()
    next_event_id = 0
    previous_on_tool_prepare = getattr(agent, "on_tool_prepare", None)
    previous_on_tool_call = getattr(agent, "on_tool_call", None)
    previous_on_tool_result = getattr(agent, "on_tool_result", None)
    previous_on_token = getattr(agent, "on_token", None)
    previous_approval_handler = getattr(agent, "approval_handler", None)

    def make_sse(event_type: str, data: Any, *, always_send: bool = False) -> str | None:
        nonlocal next_event_id
        event_id = next_event_id
        next_event_id += 1
        if not always_send and resume_from is not None and event_id <= resume_from:
            return None
        return _sse_line(event_type, data, event_id=event_id)

    async def on_tool_prepare(
        tool_name: str, params: dict[str, Any] | None, metadata: dict[str, Any]
    ) -> None:
        if metadata.get("kind") == "skill":
            event_type = "skill_prepare"
            payload = {
                "skill_name": metadata.get("skill_name"),
                "status": metadata.get("status"),
            }
        else:
            event_type = "tool_prepare"
            payload = {
                "tool_name": tool_name,
                "canonical_name": metadata.get("canonical_name"),
                "status": metadata.get("status"),
                "has_args": metadata.get("has_args", params is not None),
            }
        line = make_sse(event_type, payload)
        if line is not None:
            await queue.put(line)
        if previous_on_tool_prepare is not None:
            await previous_on_tool_prepare(tool_name, params, metadata)

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

    async def approval_handler(request: ApprovalRequest) -> str:
        if pending_approvals is None:
            return "deny"
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        pending_approvals[request.request_id] = (future, request)
        payload = {
            "request_id": request.request_id,
            "tool_name": request.tool_name,
            "canonical_name": request.canonical_name,
            "params_preview": request.params_preview(),
            "reason": request.reason,
            "risk_level": request.risk_level,
        }
        line = make_sse("approval_required", payload, always_send=True)
        if line is not None:
            await queue.put(line)
        decision = "deny"
        try:
            decision = await future
        finally:
            pending_approvals.pop(request.request_id, None)
            line = make_sse(
                "approval_resolved",
                {"request_id": request.request_id, "decision": decision},
                always_send=True,
            )
            if line is not None:
                await queue.put(line)
        return decision

    agent.on_tool_prepare = on_tool_prepare
    agent.on_tool_call = on_tool_call
    agent.on_tool_result = on_tool_result
    agent.on_token = on_token
    agent.approval_handler = approval_handler
    run_task = asyncio.create_task(agent.run(user_message))

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
            if runtime_store is not None and run_id is not None:
                try:
                    runtime_store.append_event(
                        run_id,
                        TraceEventType.RUN_FAILED,
                        {"error_type": "llm_error", "message": str(exc)},
                    )
                    runtime_store.update_run_status(
                        run_id,
                        RunStatus.FAILED,
                        error_type="llm_error",
                        error_message=str(exc),
                    )
                except Exception:
                    logger.exception("记录 Web run 失败状态失败")
            fallback = f"AI 响应异常：{exc}"
            agent.messages.append(
                Message(role=MessageRole.ASSISTANT, content=fallback)
            )
            agent._persist_message(MessageRole.ASSISTANT, fallback)
            line = make_sse("error", str(exc))
            if line is not None:
                yield line

        if background_tasks is None:
            background_tasks = set()

        title: str | None = None
        if is_new_conversation:
            title = fallback_conversation_title(first_user_message)
            _schedule_background_task(
                background_tasks,
                _persist_generated_title(
                    title_task=title_task,
                    history_store=history_store,
                    conversation_id=conversation_id,
                    first_user_message=first_user_message,
                ),
                name=f"web-title-{conversation_id}",
            )
        else:
            if not history_store.has_conversation_title(conversation_id):
                existing_first_message = (
                    history_store.get_first_user_message(conversation_id) or first_user_message
                )
                title = fallback_conversation_title(existing_first_message)
                _schedule_background_task(
                    background_tasks,
                    _backfill_conversation_title_if_missing(
                        history_store,
                        conversation_id,
                        agent.llm,
                    ),
                    name=f"web-title-backfill-{conversation_id}",
                )

        if memory_service is not None:
            _schedule_background_task(
                background_tasks,
                _finalize_memory_in_background(
                    memory_service=memory_service,
                    conversation_id=conversation_id,
                    run_id=run_id,
                    trace_recorder=agent.trace_recorder,
                ),
                name=f"web-memory-finalize-{conversation_id}",
            )

        status_value = "completed"
        if runtime_store is not None and run_id is not None:
            run = runtime_store.get_run(run_id)
            if run is not None:
                status_value = run["status"]
        yield make_sse(
            "done",
            {
                "conversation_id": conversation_id,
                "title": title,
                "run_id": run_id,
                "status": status_value,
            },
            always_send=True,
        )
    finally:
        agent.on_tool_prepare = previous_on_tool_prepare
        agent.on_tool_call = previous_on_tool_call
        agent.on_tool_result = previous_on_tool_result
        agent.on_token = previous_on_token
        agent.approval_handler = previous_approval_handler


def _sse_line(event_type: str, data: Any, event_id: int | None = None) -> str:
    payload = {
        "id": uuid4().hex if event_id is None else event_id,
        "type": event_type,
        "data": data,
    }
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _call_accepts_keyword(callable_obj: Any, name: str) -> bool:
    try:
        signature = inspect.signature(callable_obj)
    except (TypeError, ValueError):
        return True
    return name in signature.parameters or any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )


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


async def _process_rag_import(app: FastAPI, record: dict[str, Any]) -> None:
    import_id = record["import_id"]
    try:
        summary = await asyncio.to_thread(_process_rag_import_sync, app, record)
    except Exception as exc:
        logger.exception("本地知识库导入失败: %s", import_id)
        app.state.rag_imports[import_id] = {
            **record,
            "status": "failed",
            "error": str(exc),
        }
        return
    app.state.rag_imports[import_id] = {
        **record,
        "status": "completed",
        "summary": summary,
    }


def _process_rag_import_sync(app: FastAPI, record: dict[str, Any]) -> dict[str, Any]:
    root = Path(record["root"])
    import_dir = Path(record["import_dir"])
    extract_dir = Path(record["extract_dir"])
    target = root / record["source_id"]
    old_target = Path(record["existing_path"])
    backup = import_dir / "backup"
    source = {
        "source_id": record["source_id"],
        "name": record["name"],
        "description": record["description"],
        "call_when": record["call_when"],
        "path_prefix": f"{record['source_id']}/",
        "enabled": record["enabled"],
        "chunk_strategy": record["strategy"],
        "chunk_size": record["chunk_size"],
    }
    manifest = {
        "source": source,
        "target_path": str(target),
        "old_path": str(old_target),
        "backup_path": str(backup),
        "import_dir": str(import_dir),
    }
    pending_path = import_dir / "pending.json"
    pending_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    target_replaced = False

    try:
        if target.exists() and target != old_target:
            raise ValueError("目标知识库目录已存在，请重新确认覆盖")
        if old_target.exists():
            old_target.rename(backup)
        extract_dir.rename(target)
        target_replaced = True
        (target / _RAG_IMPORT_PENDING).write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
        )

        source_configs = _rag_source_configs(app.state.history_store)
        source_configs = [
            item for item in source_configs if item.source_id != source["source_id"]
        ] + [RAGSourceConfig(**source)]
        summary = RAGIndexer(
            app.state.config.rag,
            source_configs=source_configs,
        ).sync()
        (target / _RAG_IMPORT_COMPLETE).write_text(
            json.dumps(source, ensure_ascii=False), encoding="utf-8"
        )
        (target / _RAG_IMPORT_PENDING).unlink(missing_ok=True)
        app.state.history_store.upsert_rag_source(source)
        shutil.rmtree(import_dir, ignore_errors=True)
        return summary
    except Exception:
        if target_replaced and target.exists():
            shutil.rmtree(target, ignore_errors=True)
        if backup.exists() and not old_target.exists():
            backup.rename(old_target)
        try:
            RAGIndexer(
                app.state.config.rag,
                source_configs=_rag_source_configs(app.state.history_store),
            ).sync()
        except Exception:
            logger.exception("恢复本地知识库旧索引失败，将在下次启动时重建")
        raise


def _rag_source_configs(
    store: ConversationHistoryStoreSQLite,
    *,
    enabled_only: bool = False,
) -> list[RAGSourceConfig]:
    return [
        RAGSourceConfig(
            source_id=source["source_id"],
            name=source["name"],
            description=source["description"],
            call_when=source["call_when"],
            path_prefix=source["path_prefix"],
            enabled=source["enabled"],
            chunk_strategy=source.get("chunk_strategy", "heading"),
            chunk_size=int(source.get("chunk_size", 900)),
        )
        for source in store.list_rag_sources(enabled_only=enabled_only)
    ]


def _recover_rag_imports(app: FastAPI) -> None:
    for root in _rag_data_roots(app.state.config):
        imports_dir = root / ".imports"
        if imports_dir.exists():
            for import_dir in list(imports_dir.iterdir()):
                pending = import_dir / "pending.json"
                if pending.is_file():
                    _restore_pending_import(json.loads(pending.read_text(encoding="utf-8")))
                elif import_dir.is_dir():
                    shutil.rmtree(import_dir, ignore_errors=True)
            try:
                imports_dir.rmdir()
            except OSError:
                pass

        for directory in root.iterdir() if root.exists() else []:
            if not directory.is_dir():
                continue
            pending_path = directory / _RAG_IMPORT_PENDING
            complete_path = directory / _RAG_IMPORT_COMPLETE
            if pending_path.is_file():
                _restore_pending_import(json.loads(pending_path.read_text(encoding="utf-8")))
            elif complete_path.is_file():
                source = json.loads(complete_path.read_text(encoding="utf-8"))
                app.state.history_store.upsert_rag_source(source)


def _restore_pending_import(manifest: dict[str, Any]) -> None:
    target = Path(manifest["target_path"])
    old_target = Path(manifest["old_path"])
    backup = Path(manifest["backup_path"])
    if (target / _RAG_IMPORT_PENDING).is_file():
        shutil.rmtree(target, ignore_errors=True)
    if backup.exists() and not old_target.exists():
        backup.rename(old_target)
    import_dir = Path(manifest["import_dir"])
    shutil.rmtree(import_dir, ignore_errors=True)


async def _save_upload(upload: UploadFile, destination: Path) -> None:
    total = 0
    with destination.open("wb") as target:
        while chunk := await upload.read(1024 * 1024):
            total += len(chunk)
            if total > 100 * 1024 * 1024:
                raise HTTPException(status_code=413, detail="压缩包超过 100MB 限制。")
            target.write(chunk)


def _validate_rag_source_id(value: str) -> str:
    normalized = value.strip()
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", normalized):
        raise HTTPException(status_code=422, detail="标识必须是小写字母开头的安全标识。")
    return normalized


def _archive_stem(filename: str) -> str:
    name = Path(filename.replace("\\", "/")).name
    stem = Path(name).stem
    stem = re.sub(r"[^\w\-.\u4e00-\u9fff]", "_", stem, flags=re.UNICODE).strip("._")
    return stem or "upload"


def _rag_import_conflicts(app: FastAPI, source_id: str) -> bool:
    if app.state.history_store.get_rag_source(source_id) is not None:
        return True
    return any((root / source_id).exists() for root in _rag_data_roots(app.state.config))


def _rag_import_root(app: FastAPI, source_id: str) -> Path:
    source = app.state.history_store.get_rag_source(source_id)
    candidates = _rag_data_roots(app.state.config)
    if source is not None:
        prefix = source["path_prefix"].rstrip("/")
        matching = [root for root in candidates if (root / prefix).exists()]
        if len(matching) == 1:
            return matching[0]
    matching = [root for root in candidates if (root / source_id).exists()]
    return matching[0] if len(matching) == 1 else candidates[0]


def _rag_existing_path(app: FastAPI, source_id: str, root: Path) -> Path:
    source = app.state.history_store.get_rag_source(source_id)
    if source is None:
        return root / source_id
    prefix = source["path_prefix"].rstrip("/")
    return root / prefix


def _get_rag_import(app: FastAPI, import_id: str) -> dict[str, Any]:
    record = app.state.rag_imports.get(import_id)
    if record is None:
        raise HTTPException(status_code=404, detail="导入任务不存在或已清理。")
    return record


def _build_import_tree(root: Path) -> list[dict[str, Any]]:
    def build(directory: Path) -> list[dict[str, Any]]:
        nodes: list[dict[str, Any]] = []
        for path in sorted(directory.iterdir(), key=lambda item: (item.is_file(), item.name.casefold())):
            relative = path.relative_to(root).as_posix()
            node: dict[str, Any] = {
                "name": path.name,
                "path": relative,
                "type": "file" if path.is_file() else "directory",
            }
            if path.is_dir():
                node["children"] = build(path)
            nodes.append(node)
        return nodes

    return [{
        "name": root.name,
        "path": root.name,
        "type": "directory",
        "children": build(root),
    }]


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


def _validate_rag_source_text(value: str) -> str:
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("本地知识库文本不能包含换行或控制字符。")
    return value


def _normalize_rag_source_path(config: AppConfig, raw_path: str) -> str:
    path = raw_path.strip()
    if not path or "\\" in path:
        raise HTTPException(status_code=422, detail="数据源目录路径不合法。")
    pure_path = PurePosixPath(path)
    if pure_path.is_absolute() or len(pure_path.parts) != 1 or pure_path.parts[0] in {".", ".."}:
        raise HTTPException(status_code=422, detail="数据源目录必须是已存在的一级目录。")

    normalized = f"{pure_path.parts[0]}/"
    if not any(
        (candidate := (root / pure_path.parts[0]).resolve()).is_dir()
        and candidate.is_relative_to(root)
        for root in _rag_data_roots(config)
    ):
        raise HTTPException(status_code=422, detail="数据源目录不存在于本地 RAG 根目录中。")
    return normalized


def _parse_metadata_fragment(raw_metadata: str) -> dict[str, Any]:
    if not raw_metadata.strip():
        return {}
    try:
        metadata = yaml.safe_load(raw_metadata)
    except yaml.YAMLError as exc:
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
    frontmatter: dict[str, Any] = {
        "name": request.name,
        "description": request.description,
    }
    if request.license is not None:
        frontmatter["license"] = request.license
    if request.compatibility is not None:
        frontmatter["compatibility"] = request.compatibility
    if request.allowed_tools:
        frontmatter["allowed-tools"] = " ".join(request.allowed_tools)
    if metadata:
        frontmatter["metadata"] = metadata
    serialized = yaml.dump(
        frontmatter,
        Dumper=_SkillYamlDumper,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    ).rstrip()
    content = request.content.rstrip()
    return f"---\n{serialized}\n---\n\n{content}\n"


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
    parameters = {
        "type": "object",
        "properties": json_schema.get("properties", {}),
        "required": json_schema.get("required", []),
    }
    if "additionalProperties" in json_schema:
        parameters["additionalProperties"] = json_schema["additionalProperties"]
    return parameters


def _new_web_conversation_id() -> str:
    from uuid import uuid4

    return uuid4().hex


def main() -> None:
    import uvicorn

    clear_proxy_env()
    config = AppConfig()
    setup_logger(level=config.log_level)
    uvicorn.run(create_app(config), host="127.0.0.1", port=8081)
