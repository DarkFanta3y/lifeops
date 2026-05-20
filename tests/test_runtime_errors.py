from __future__ import annotations

from lifeops.runtime.errors import AgentRuntimeError, RuntimeErrorType, to_trace_payload


def test_runtime_error_types_are_serializable():
    assert RuntimeErrorType.LLM_ERROR.value == "llm_error"
    assert RuntimeErrorType.MAX_ITERATIONS_REACHED.value == "max_iterations_reached"


def test_agent_runtime_error_converts_to_trace_payload():
    error = AgentRuntimeError(
        RuntimeErrorType.TOOL_ERROR,
        "工具失败",
        recoverable=True,
        details={"tool_name": "bash"},
    )

    payload = to_trace_payload(error)

    assert payload == {
        "error_type": "tool_error",
        "message": "工具失败",
        "recoverable": True,
        "details": {"tool_name": "bash"},
    }
