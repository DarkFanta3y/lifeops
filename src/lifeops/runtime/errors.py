from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RuntimeErrorType(str, Enum):
    LLM_ERROR = "llm_error"
    LLM_PARSE_ERROR = "llm_parse_error"
    TOOL_ERROR = "tool_error"
    TOOL_TIMEOUT = "tool_timeout"
    POLICY_DENIED = "policy_denied"
    MCP_ERROR = "mcp_error"
    RAG_ERROR = "rag_error"
    CONTEXT_ERROR = "context_error"
    MAX_ITERATIONS_REACHED = "max_iterations_reached"
    UNKNOWN_ERROR = "unknown_error"


@dataclass(frozen=True)
class AgentRuntimeError(Exception):
    error_type: RuntimeErrorType
    message: str
    recoverable: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return self.message


def to_trace_payload(exc: BaseException | AgentRuntimeError) -> dict[str, Any]:
    if isinstance(exc, AgentRuntimeError):
        return {
            "error_type": exc.error_type.value,
            "message": exc.message,
            "recoverable": exc.recoverable,
            "details": exc.details,
        }
    return {
        "error_type": RuntimeErrorType.UNKNOWN_ERROR.value,
        "message": str(exc),
        "recoverable": False,
        "details": {},
    }
