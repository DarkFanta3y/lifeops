from __future__ import annotations

from lifeops.runtime.store import RuntimeStore
from lifeops.runtime.types import AgentRun, RunStatus, TraceEvent, TraceEventType
from lifeops.storage.sqlite_store import ConversationHistoryStoreSQLite


def test_runtime_types_can_be_imported():
    assert RunStatus.RUNNING.value == "running"
    assert TraceEventType.RUN_STARTED.value == "run_started"
    assert AgentRun.__dataclass_params__.frozen is True
    assert TraceEvent.__dataclass_params__.frozen is True


def test_runtime_store_creates_run_and_orders_trace_events(tmp_path):
    store = ConversationHistoryStoreSQLite(tmp_path / "runtime.db")
    runtime = RuntimeStore(store, trace_max_payload_chars=80)

    run = runtime.create_run(
        conversation_id="conv-1",
        source="web",
        user_input="请帮我规划今天",
        run_id="run-1",
    )
    assert run.status == RunStatus.RUNNING

    first = runtime.append_event("run-1", TraceEventType.RUN_STARTED, {"input_length": 7})
    second = runtime.append_event("run-1", TraceEventType.LLM_CALL_STARTED, {"iteration": 0})
    assert first.sequence == 0
    assert second.sequence == 1

    runtime.update_run_status("run-1", RunStatus.COMPLETED, final_output="已完成")

    stored_run = runtime.get_run("run-1")
    assert stored_run is not None
    assert stored_run["status"] == "completed"
    assert stored_run["final_output"] == "已完成"

    events = runtime.list_run_events("run-1")
    assert [event["sequence"] for event in events] == [0, 1]
    assert [event["event_type"] for event in events] == ["run_started", "llm_call_started"]


def test_runtime_store_truncates_large_payload_and_lists_conversation_runs(tmp_path):
    store = ConversationHistoryStoreSQLite(tmp_path / "runtime.db")
    runtime = RuntimeStore(store, trace_max_payload_chars=1000)
    runtime.create_run("conv-1", "web", "x", run_id="run-a")
    runtime.create_run("conv-1", "web", "y", run_id="run-b")

    runtime.append_event("run-a", TraceEventType.TOOL_RESULT, {"output": "x" * 5000})

    event = runtime.list_run_events("run-a")[0]
    assert event["payload"]["truncated"] is True
    assert len(event["payload_json"]) <= 1200

    runs = runtime.list_conversation_runs("conv-1")
    assert [run["run_id"] for run in runs] == ["run-b", "run-a"]
