from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class RunStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TraceEventType(str, Enum):
    RUN_STARTED = "run_started"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"
    LLM_CALL_STARTED = "llm_call_started"
    LLM_CALL_FINISHED = "llm_call_finished"
    LLM_PARSE_ERROR = "llm_parse_error"
    LLM_ERROR = "llm_error"
    RETRIEVAL_ROUTE_DECIDED = "retrieval_route_decided"
    TOOL_REQUESTED = "tool_requested"
    TOOL_POLICY_DECISION = "tool_policy_decision"
    TOOL_RESULT = "tool_result"
    TOOL_ERROR = "tool_error"
    TOOL_TIMEOUT = "tool_timeout"
    MCP_ERROR = "mcp_error"
    CONTEXT_COMPRESSED = "context_compressed"
    MEMORY_BOOTSTRAP_STARTED = "memory_bootstrap_started"
    MEMORY_BOOTSTRAP_FINISHED = "memory_bootstrap_finished"
    MEMORY_BOOTSTRAP_FAILED = "memory_bootstrap_failed"
    MEMORY_FINALIZE_STARTED = "memory_finalize_started"
    MEMORY_FINALIZE_FINISHED = "memory_finalize_finished"
    MEMORY_FINALIZE_SKIPPED = "memory_finalize_skipped"
    MEMORY_FINALIZE_FAILED = "memory_finalize_failed"
    SKILL_MATCHED = "skill_matched"


@dataclass(frozen=True)
class AgentRun:
    run_id: str
    conversation_id: str
    source: str
    status: RunStatus
    user_input: str
    started_at: str
    final_output: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    ended_at: str | None = None


@dataclass(frozen=True)
class TraceEvent:
    event_id: str
    run_id: str
    event_type: TraceEventType
    sequence: int
    payload: dict[str, Any]
    created_at: str


@dataclass(frozen=True)
class TraceRecorder:
    store: Any
    run_id: str | None = None

    def record(
        self,
        event_type: TraceEventType | str,
        payload: dict[str, Any] | None = None,
        *,
        run_id: str | None = None,
    ) -> TraceEvent | None:
        effective_run_id = run_id or self.run_id
        if not effective_run_id:
            return None
        return self.store.append_event(effective_run_id, event_type, payload or {})
