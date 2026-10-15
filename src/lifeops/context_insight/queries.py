"""上下文洞察的读侧：把快照、运行轨迹与工具调用折叠成面板所需的数据（形态对齐 dsh-context 的 Snapshot）。"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from lifeops.context_insight.composition import CATEGORIES

ELEMENT_TEXT_MAX_CHARS = 20000
EXCERPT_CHARS = 80
HEATMAP_DAYS = 56
USAGE_DAYS = 7
RANGE_DAYS = {"7d": 7, "30d": 30}

FILE_TOOLS = {
    "file_read": "read",
    "file_create": "write",
    "file_replace": "write",
    "file_append": "write",
    "grep": "search",
    "glob": "search",
}
GREP_LINE = re.compile(r"^(.+?):(\d+):")
COMPACTION_PHASES = {"offload", "summarize", "critical"}


def _loads(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return default


def _iso_ms(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(datetime.fromisoformat(value).timestamp() * 1000)
    except ValueError:
        return None


def _day_key(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d")


def _excerpt(text: str | None, limit: int = EXCERPT_CHARS) -> str:
    return " ".join((text or "").split())[:limit]


def _line_count(text: Any) -> int:
    if not isinstance(text, str) or not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def _brief_node(element: dict[str, Any]) -> dict[str, Any]:
    node = {"cat": element.get("cat"), "name": element.get("name") or "", "tokens": element.get("tokens") or 0}
    for key in ("tool", "calls", "call"):
        if element.get(key):
            node[key] = element[key]
    return node


def _cats(raw: str | None) -> dict[str, int]:
    data = _loads(raw, {})
    return {cat: int(data.get(cat) or 0) for cat in CATEGORIES}


class UsageTotals:
    """厂商实际 usage 的累计：未缓存输入 / 缓存命中 / 输出，三者互斥。"""

    def __init__(self) -> None:
        self.uncached = 0
        self.cache_read = 0
        self.output = 0
        self.samples = 0

    def add(self, usage: dict[str, int] | None) -> None:
        if not usage:
            return
        prompt = int(usage.get("prompt_tokens") or 0)
        cached = min(prompt, int(usage.get("cached_tokens") or 0))
        self.uncached += prompt - cached
        self.cache_read += cached
        self.output += int(usage.get("completion_tokens") or 0)
        self.samples += 1

    @property
    def billed(self) -> int:
        return self.uncached + self.cache_read + self.output

    def to_dict(self) -> dict[str, int]:
        return {
            "uncachedInputTokens": self.uncached,
            "cacheReadTokens": self.cache_read,
            "cacheWriteTokens": 0,
            "outputTokens": self.output,
        }


class ContextInsightQueries:
    def __init__(self, sqlite_store: Any, prices: dict[str, float | None] | None = None) -> None:
        self.sqlite_store = sqlite_store
        self.prices = prices or {}

    @property
    def _conn(self) -> sqlite3.Connection:
        return self.sqlite_store._conn

    # ---- 费用 ----

    def _priced(self) -> bool:
        return self.prices.get("input") is not None

    def cost_of(self, totals: UsageTotals) -> float | None:
        if not self._priced():
            return None
        input_price = float(self.prices.get("input") or 0)
        cache_price = self.prices.get("cache")
        cache_price = input_price if cache_price is None else float(cache_price)
        output_price = float(self.prices.get("output") or input_price)
        return round(
            (totals.uncached * input_price + totals.cache_read * cache_price
             + totals.output * output_price) / 1_000_000,
            6,
        )

    def price_info(self) -> dict[str, float | None] | None:
        return dict(self.prices) if self._priced() else None

    # ---- 公共读取 ----

    def _runs(self, conversation_id: str) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT run_id, status, user_input, started_at, ended_at FROM agent_runs "
            "WHERE conversation_id = ? ORDER BY started_at, rowid",
            (conversation_id,),
        ).fetchall()

    def _snapshots(self, conversation_id: str) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM context_snapshots WHERE conversation_id = ? ORDER BY id",
            (conversation_id,),
        ).fetchall()

    def _traces(self, conversation_id: str, event_types: tuple[str, ...]) -> list[dict[str, Any]]:
        placeholders = ",".join("?" * len(event_types))
        rows = self._conn.execute(
            "SELECT e.run_id, e.event_type, e.payload_json, e.created_at FROM agent_trace_events e "
            "JOIN agent_runs r ON r.run_id = e.run_id "
            f"WHERE r.conversation_id = ? AND e.event_type IN ({placeholders}) "
            "ORDER BY r.started_at, e.sequence",
            (conversation_id, *event_types),
        ).fetchall()
        return [
            {
                "run_id": row["run_id"],
                "type": row["event_type"],
                "payload": _loads(row["payload_json"], {}),
                "time": _iso_ms(row["created_at"]),
            }
            for row in rows
        ]

    def _run_wall_ms(self, run: sqlite3.Row) -> int:
        start = _iso_ms(run["started_at"])
        if start is None:
            return 0
        end = _iso_ms(run["ended_at"])
        if end is None:
            end = int(time.time() * 1000) if run["status"] in {"running", "waiting_approval"} else start
        return max(0, end - start)

    # ---- 会话头数据 ----

    def head(self, conversation_id: str) -> dict[str, Any]:
        runs = self._runs(conversation_id)
        turn_of = {run["run_id"]: index + 1 for index, run in enumerate(runs)}
        run_input = {run["run_id"]: run["user_input"] for run in runs}
        snapshots = self._snapshots(conversation_id)
        main = [row for row in snapshots if row["agent_id"] == "main"]
        own_usage, family_usage = UsageTotals(), UsageTotals()
        requests = []
        previous_hashes: set[str] = set()
        previous_run = None
        step = 0
        for row in main:
            # 步序号在轮内计数（与 dsh-context 的 T{轮} S{步} 一致）
            step = step + 1 if row["run_id"] == previous_run else 1
            cats = _cats(row["categories_json"])
            usage = _loads(row["usage_json"], None)
            own_usage.add(usage)
            elements = _loads(row["elements_json"], [])
            hashes = {element.get("hash") for element in elements}
            inputs = [] if row["run_id"] != previous_run else [
                _brief_node(element) for element in elements
                if element.get("cat") not in {"system", "tools", "user"} and element.get("hash") not in previous_hashes
            ]
            previous_hashes, previous_run = hashes, row["run_id"]
            record: dict[str, Any] = {
                "id": row["id"],
                "seq": row["id"],
                "runId": row["run_id"],
                "turn": turn_of.get(row["run_id"], 0),
                "step": step,
                "iteration": row["iteration"],
                "time": row["started_at_ms"],
                "model": row["model"],
                **cats,
                "total": sum(cats.values()),
                "estimated": row["estimated_tokens"],
                "budget": row["budget"],
            }
            if usage:
                prompt = int(usage.get("prompt_tokens") or 0)
                record["prompt"] = prompt
                record["cacheRead"] = int(usage.get("cached_tokens") or 0)
                record["output"] = int(usage.get("completion_tokens") or 0)
            if row["duration_ms"] is not None:
                record["activeMs"] = row["duration_ms"]
            if row["ttft_ms"] is not None:
                record["ttftMs"] = row["ttft_ms"]
            record["brief"] = {
                "opener": _excerpt(run_input.get(row["run_id"]), 120),
                "inputs": inputs,
            }
            response = _loads(row["response_json"], None)
            if response:
                record["response"] = response
            if row["trimmed_count"] or row["truncated_count"]:
                record["trimmed"] = row["trimmed_count"]
                record["truncated"] = row["truncated_count"]
            requests.append(record)
        for row in snapshots:
            family_usage.add(_loads(row["usage_json"], None))

        latest = main[-1] if main else None
        current = dict.fromkeys(CATEGORIES, 0)
        tool_calls = 0
        if latest is not None:
            current = _cats(latest["categories_json"])
            elements = _loads(latest["elements_json"], [])
            tool_calls = sum(1 for element in elements if element.get("cat") == "tool")
        answers = self._conn.execute(
            "SELECT COUNT(*) FROM messages WHERE conversation_id = ? AND role = 'assistant' "
            "AND intermediate = 0 AND (record_type IS NULL OR record_type = '')",
            (conversation_id,),
        ).fetchone()[0]

        tool_traces = self._traces(conversation_id, ("tool_result",))
        timing = self._timing(main, runs, tool_traces)
        result: dict[str, Any] = {
            "ok": True,
            "hasSnapshots": bool(main),
            "model": latest["model"] if latest is not None else None,
            "contextWindow": latest["budget"] if latest is not None else None,
            "reserveRatio": latest["reserve_ratio"] if latest is not None else None,
            "current": {**current, "total": sum(current.values())},
            "estimated": latest["estimated_tokens"] if latest is not None else 0,
            "toolCalls": tool_calls,
            "humanInputs": len(runs),
            "answers": answers,
            "lastUser": _excerpt(runs[-1]["user_input"]) if runs else "",
            "running": bool(runs) and runs[-1]["status"] in {"running", "waiting_approval"},
            "requests": requests,
            "events": self._events(conversation_id, main, requests),
            "usage": own_usage.to_dict(),
            "familyUsage": family_usage.to_dict(),
            "agents": len({row["agent_id"] for row in snapshots}),
            "cost": self.cost_of(own_usage),
            "familyCost": self.cost_of(family_usage),
            "prices": self.price_info(),
            "timing": timing["totals"],
            "spans": timing["spans"],
        }
        return result

    def _timing(
        self, main: list[sqlite3.Row], runs: list[sqlite3.Row], tool_traces: list[dict[str, Any]]
    ) -> dict[str, Any]:
        totals: dict[str, Any] = {
            "wallMs": sum(self._run_wall_ms(run) for run in runs),
            "ttftMs": 0, "genMs": 0, "calls": 0, "toolsMs": 0, "toolCalls": 0,
            "speedTokens": 0, "speedMs": 0, "tools": {},
        }
        spans: list[dict[str, Any]] = []
        for row in main:
            duration = row["duration_ms"]
            if duration is None:
                continue
            start = row["started_at_ms"]
            ttft = row["ttft_ms"] if row["ttft_ms"] is not None else 0
            ttft = min(ttft, duration)
            totals["calls"] += 1
            totals["ttftMs"] += ttft
            totals["genMs"] += duration - ttft
            if ttft:
                spans.append({"kind": "ttft", "start": start, "end": start + ttft})
            if duration > ttft:
                spans.append({"kind": "text", "start": start + ttft, "end": start + duration})
            usage = _loads(row["usage_json"], None)
            if usage and row["ttft_ms"] is not None and duration > ttft:
                totals["speedTokens"] += int(usage.get("completion_tokens") or 0)
                totals["speedMs"] += duration - ttft
        tools: dict[str, dict[str, float]] = defaultdict(lambda: {"calls": 0, "ms": 0})
        for trace in tool_traces:
            payload = trace["payload"]
            ms = float(payload.get("duration_ms") or 0)
            name = str(payload.get("tool_name") or "?")
            tools[name]["calls"] += 1
            tools[name]["ms"] += ms
            totals["toolsMs"] += ms
            totals["toolCalls"] += 1
            end = payload.get("ended_at_ms")
            if isinstance(end, int) and ms > 0:
                spans.append({"kind": "tools", "start": end - round(ms), "end": end})
        totals["toolsMs"] = round(totals["toolsMs"])
        totals["tools"] = {name: {"calls": int(v["calls"]), "ms": round(v["ms"])} for name, v in tools.items()}
        spans.sort(key=lambda span: span["start"])
        return {"totals": totals, "spans": spans}

    def _events(
        self, conversation_id: str, main: list[sqlite3.Row], requests: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for row in self._conn.execute(
            "SELECT phase, freed_tokens, reason, created_at FROM compression_events "
            "WHERE conversation_id = ? ORDER BY id",
            (conversation_id,),
        ).fetchall():
            phase = row["phase"]
            if phase not in COMPACTION_PHASES and phase != "trim":
                continue
            events.append({
                "time": _iso_ms(row["created_at"]) or 0,
                "kind": "prune" if phase == "trim" else "compaction",
                "form": phase,
                "tokens": row["freed_tokens"],
                "detail": row["reason"],
            })
        skill_tokens = self._skill_tokens(main)
        for trace in self._traces(conversation_id, ("skill_matched", "task_complexity_decided", "todo_updated")):
            payload = trace["payload"]
            if trace["type"] == "skill_matched":
                name = str(payload.get("skill_name") or "?")
                event = {"time": trace["time"] or 0, "kind": "inject", "sub": "skill", "name": name,
                         "form": payload.get("activation_type")}
                tokens = skill_tokens.get(name)
                if tokens:
                    event["tokens"] = tokens
                events.append(event)
            elif trace["type"] == "task_complexity_decided" and payload.get("plan_required"):
                events.append({"time": trace["time"] or 0, "kind": "mode", "name": "plan.on"})
            elif trace["type"] == "todo_updated":
                events.append({"time": trace["time"] or 0, "kind": "mode", "name": "plan.update",
                               "count": payload.get("todo_count")})
        previous_model = None
        for request in requests:
            if request.get("trimmed") or request.get("truncated"):
                events.append({
                    "time": request["time"], "kind": "prune", "form": "budget",
                    "count": int(request.get("trimmed", 0)) + int(request.get("truncated", 0)),
                    "detail": f"裁剪历史消息 {request.get('trimmed', 0)} 条，截断工具输出 {request.get('truncated', 0)} 条",
                })
            model = request.get("model")
            if previous_model is not None and model and model != previous_model:
                events.append({"time": request["time"], "kind": "model", "from": previous_model, "to": model})
            previous_model = model or previous_model
        events.sort(key=lambda event: event["time"])
        for seq, event in enumerate(events, start=1):
            event["seq"] = seq
            target = next((r for r in requests if r["time"] >= event["time"]), None)
            if target is not None:
                event["turn"], event["step"] = target["turn"], target["step"]
            before = [r for r in requests if r["time"] < event["time"]]
            if before:
                event["fromTurn"], event["fromStep"] = before[-1]["turn"], before[-1]["step"]
        return events

    def _skill_tokens(self, main: list[sqlite3.Row]) -> dict[str, int]:
        tokens: dict[str, int] = {}
        for row in main:
            for element in _loads(row["elements_json"], []):
                name = str(element.get("name") or "")
                if element.get("cat") == "skill" and name.startswith("skill:"):
                    tokens.setdefault(name[len("skill:"):], int(element.get("tokens") or 0))
        return tokens

    # ---- 浏览器详情 ----

    def snapshot_detail(self, snapshot_id: int) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM context_snapshots WHERE id = ?", (snapshot_id,)).fetchone()
        if row is None:
            return None
        previous = self._conn.execute(
            "SELECT categories_json, elements_json FROM context_snapshots "
            "WHERE conversation_id = ? AND agent_id = ? AND id < ? ORDER BY id DESC LIMIT 1",
            (row["conversation_id"], row["agent_id"], snapshot_id),
        ).fetchone()
        elements = _loads(row["elements_json"], [])
        hashes = {element.get("hash") for element in elements}
        blobs = self._blobs(hashes)
        previous_hashes: set[str] = set()
        delta: dict[str, dict[str, int]] | None = None
        if previous is not None:
            previous_elements = _loads(previous["elements_json"], [])
            previous_hashes = {element.get("hash") for element in previous_elements}
            delta = {}
            for cat in CATEGORIES:
                now = [e for e in elements if e.get("cat") == cat]
                before = [e for e in previous_elements if e.get("cat") == cat]
                delta[cat] = {
                    "items": len(now) - len(before),
                    "tokens": sum(int(e.get("tokens") or 0) for e in now)
                    - sum(int(e.get("tokens") or 0) for e in before),
                }
        served = []
        for index, element in enumerate(elements):
            content = dict(blobs.get(element.get("hash"), {}))
            text = content.get("text")
            if isinstance(text, str) and len(text) > ELEMENT_TEXT_MAX_CHARS:
                content["text"] = text[:ELEMENT_TEXT_MAX_CHARS]
                content["clipped"] = len(text)
            served.append({
                **element,
                "key": f"{element.get('cat')}:{index}",
                "content": content,
                "isNew": previous is not None and element.get("hash") not in previous_hashes,
            })
        return {
            "id": row["id"],
            "conversationId": row["conversation_id"],
            "agentId": row["agent_id"],
            "iteration": row["iteration"],
            "time": row["started_at_ms"],
            "model": row["model"],
            "budget": row["budget"],
            "categories": _cats(row["categories_json"]),
            "usage": _loads(row["usage_json"], None),
            "response": _loads(row["response_json"], None),
            "elements": served,
            "delta": delta,
        }

    def _blobs(self, hashes: set[Any]) -> dict[str, dict[str, Any]]:
        keys = [h for h in hashes if isinstance(h, str)]
        if not keys:
            return {}
        placeholders = ",".join("?" * len(keys))
        rows = self._conn.execute(
            f"SELECT hash, content FROM context_blobs WHERE hash IN ({placeholders})", keys
        ).fetchall()
        return {row["hash"]: _loads(row["content"], {}) for row in rows}

    # ---- 文件活动 ----

    def files(self, conversation_id: str) -> dict[str, Any]:
        rows = self._conn.execute(
            "SELECT tc.tool_call_id, tc.tool_name, tc.arguments, m.created_at, m.id AS message_id "
            "FROM tool_calls tc JOIN messages m ON m.id = tc.message_id "
            f"WHERE m.conversation_id = ? AND tc.tool_name IN ({','.join('?' * len(FILE_TOOLS))}) "
            "ORDER BY m.id",
            (conversation_id, *FILE_TOOLS),
        ).fetchall()
        results = {
            row["tool_call_id"]: row
            for row in self._conn.execute(
                "SELECT id, tool_call_id, content, created_at FROM messages "
                "WHERE conversation_id = ? AND role = 'tool' AND tool_call_id IS NOT NULL",
                (conversation_id,),
            ).fetchall()
        }
        snapshot_of_call = self._snapshot_of_call(conversation_id)
        ops: list[dict[str, Any]] = []
        for row in rows:
            result = results.get(row["tool_call_id"])
            if result is None:
                continue
            args = _loads(row["arguments"], {})
            if not isinstance(args, dict):
                continue
            output = result["content"] or ""
            base = {
                "seq": result["id"],
                "tool": row["tool_name"],
                "time": _iso_ms(result["created_at"]),
                "err": output.startswith("Error"),
                "callId": row["tool_call_id"],
                "snapshot": snapshot_of_call.get(row["tool_call_id"]),
                "added": 0,
                "removed": 0,
            }
            ops.extend(self._ops_of_call(row["tool_name"], args, output, base))
        return {"root": os.getcwd(), "ops": ops}

    def _ops_of_call(
        self, tool: str, args: dict[str, Any], output: str, base: dict[str, Any]
    ) -> list[dict[str, Any]]:
        kind = FILE_TOOLS[tool]
        path = str(args.get("path") or ".")
        if tool == "file_read":
            offset = int(args.get("offset") or 1)
            count = 0 if base["err"] else _line_count(output)
            return [{**base, "kind": kind, "path": path, "read": {"start": offset, "count": count}}]
        if tool in {"file_create", "file_append"}:
            return [{**base, "kind": kind, "path": path, "added": _line_count(args.get("content"))}]
        if tool == "file_replace":
            return [{**base, "kind": kind, "path": path,
                     "added": _line_count(args.get("new_text")), "removed": _line_count(args.get("old_text"))}]
        pattern = str(args.get("pattern") or "")
        detail = pattern + (f" ({args['glob']})" if args.get("glob") else "")
        if tool == "grep" and not base["err"]:
            hits: dict[str, int] = defaultdict(int)
            for line in output.splitlines():
                match = GREP_LINE.match(line)
                if match:
                    hits[match.group(1)] += 1
            if hits:
                return [{**base, "kind": kind, "path": file, "detail": detail, "hits": count}
                        for file, count in hits.items()]
        return [{**base, "kind": kind, "path": pattern or path, "detail": detail, "pattern": True}]

    def _snapshot_of_call(self, conversation_id: str) -> dict[str, int]:
        found: dict[str, int] = {}
        for row in self._conn.execute(
            "SELECT id, elements_json FROM context_snapshots WHERE conversation_id = ? "
            "AND agent_id = 'main' ORDER BY id",
            (conversation_id,),
        ).fetchall():
            for element in _loads(row["elements_json"], []):
                call = element.get("call")
                if element.get("cat") == "tool" and isinstance(call, str):
                    found.setdefault(call, row["id"])
        return found

    # ---- 子 Agent 编队 ----

    def fleet(self, conversation_id: str) -> dict[str, Any]:
        title_row = self._conn.execute(
            "SELECT title FROM conversations WHERE conversation_id = ?", (conversation_id,)
        ).fetchone()
        title = title_row["title"] if title_row is not None else None
        runs = self._runs(conversation_id)
        snapshots = self._snapshots(conversation_id)
        by_agent: dict[str, list[sqlite3.Row]] = defaultdict(list)
        for row in snapshots:
            by_agent[row["agent_id"]].append(row)

        def card(agent_id: str) -> dict[str, Any]:
            rows = by_agent.get(agent_id, [])
            usage = UsageTotals()
            for row in rows:
                usage.add(_loads(row["usage_json"], None))
            latest = rows[-1] if rows else None
            current = _cats(latest["categories_json"]) if latest is not None else dict.fromkeys(CATEGORIES, 0)
            return {
                "steps": len(rows),
                "current": {**current, "total": sum(current.values())},
                "window": latest["budget"] if latest is not None else 0,
                "model": latest["model"] if latest is not None else None,
                "billed": usage.billed,
                "cost": self.cost_of(usage),
                "lastActive": latest["started_at_ms"] if latest is not None else None,
            }

        last_status = runs[-1]["status"] if runs else "completed"
        agents = [{
            "id": "main",
            "parent": None,
            "title": title or "主智能体",
            "kind": "main",
            "status": "running" if last_status in {"running", "waiting_approval"} else "done",
            "startedAt": _iso_ms(runs[0]["started_at"]) if runs else None,
            "durationMs": sum(self._run_wall_ms(run) for run in runs),
            "prompt": runs[0]["user_input"] if runs else "",
            **card("main"),
        }]
        subagents: dict[str, dict[str, Any]] = {}
        for trace in self._traces(conversation_id, ("subagent_started", "subagent_finished")):
            payload = trace["payload"]
            agent_id = payload.get("agent_id")
            if not isinstance(agent_id, str):
                continue
            if trace["type"] == "subagent_started":
                subagents[agent_id] = {
                    "id": agent_id,
                    "parent": "main",
                    "title": payload.get("description") or "子智能体",
                    "kind": "subagent",
                    "status": "running" if last_status in {"running", "waiting_approval"} else "unknown",
                    "startedAt": trace["time"],
                    "prompt": payload.get("prompt") or "",
                    "tools": payload.get("tools") or [],
                    "durationMs": None,
                }
            elif agent_id in subagents:
                subagents[agent_id].update({
                    "status": "done",
                    "durationMs": payload.get("duration_ms"),
                    "output": payload.get("output") or "",
                })
        for agent in subagents.values():
            agents.append({**agent, **card(agent["id"])})
        return {"agents": agents, "todos": self._latest_todos(conversation_id)}

    def _latest_todos(self, conversation_id: str) -> list[dict[str, Any]]:
        row = self._conn.execute(
            "SELECT tc.arguments FROM tool_calls tc JOIN messages m ON m.id = tc.message_id "
            "WHERE m.conversation_id = ? AND tc.tool_name = 'todo_write' ORDER BY m.id DESC LIMIT 1",
            (conversation_id,),
        ).fetchone()
        todos = _loads(row["arguments"], {}).get("todos") if row is not None else None
        return [todo for todo in todos if isinstance(todo, dict)] if isinstance(todos, list) else []

    # ---- 跨会话总览 ----

    def overview(self, range_key: str = "7d") -> dict[str, Any]:
        now = datetime.now()
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        days = RANGE_DAYS.get(range_key)
        since = int((today - timedelta(days=days - 1)).timestamp() * 1000) if days else 0
        heat_since = int((today - timedelta(days=HEATMAP_DAYS - 1)).timestamp() * 1000)
        rows = self._conn.execute(
            "SELECT s.conversation_id, s.run_id, s.agent_id, s.categories_json, s.usage_json, "
            "s.started_at_ms, s.budget, c.title, c.updated_at FROM context_snapshots s "
            "LEFT JOIN conversations c ON c.conversation_id = s.conversation_id "
            "WHERE s.started_at_ms >= ? ORDER BY s.id",
            (min(since, heat_since),),
        ).fetchall()

        daily: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"requests": 0, "usage": UsageTotals(), "sessions": set()}
        )
        sessions: dict[str, dict[str, Any]] = {}
        range_usage = UsageTotals()
        requests = 0
        for row in rows:
            usage = _loads(row["usage_json"], None)
            day = _day_key(row["started_at_ms"])
            bucket = daily[day]
            bucket["requests"] += 1
            bucket["usage"].add(usage)
            bucket["sessions"].add(row["conversation_id"])
            if row["started_at_ms"] < since:
                continue
            requests += 1
            range_usage.add(usage)
            session = sessions.setdefault(row["conversation_id"], {
                "conversationId": row["conversation_id"],
                "title": row["title"] or "未命名对话",
                "updatedAt": _iso_ms(row["updated_at"]),
                "usage": UsageTotals(),
                "requests": 0,
                "runs": set(),
                "days": set(),
                "current": dict.fromkeys(CATEGORIES, 0),
                "window": 0,
                "lastActive": 0,
            })
            session["usage"].add(usage)
            session["requests"] += 1
            session["runs"].add(row["run_id"])
            session["days"].add(day)
            session["lastActive"] = max(session["lastActive"], row["started_at_ms"])
            if row["agent_id"] == "main":
                session["current"] = _cats(row["categories_json"])
                session["window"] = row["budget"]

        composition = dict.fromkeys(CATEGORIES, 0)
        cards = []
        for session in sessions.values():
            for cat, value in session["current"].items():
                composition[cat] += value
            usage = session.pop("usage")
            cards.append({
                **session,
                "runs": len(session["runs"]),
                "days": sorted(session["days"]),
                "current": {**session["current"], "total": sum(session["current"].values())},
                "billed": usage.billed,
                "cost": self.cost_of(usage),
            })
        cards.sort(key=lambda card: card["lastActive"], reverse=True)

        def day_row(offset: int) -> dict[str, Any]:
            key = (today - timedelta(days=offset)).strftime("%Y-%m-%d")
            bucket = daily.get(key)
            usage = bucket["usage"] if bucket else UsageTotals()
            return {
                "day": key,
                "tokens": usage.billed,
                "requests": bucket["requests"] if bucket else 0,
                "sessions": len(bucket["sessions"]) if bucket else 0,
                "cost": self.cost_of(usage),
            }

        prompt_total = range_usage.uncached + range_usage.cache_read
        return {
            "range": range_key if days else "all",
            "kpi": {
                "sessions": len(cards),
                "requests": requests,
                "billed": range_usage.billed,
                "cost": self.cost_of(range_usage),
                "cacheHit": round(range_usage.cache_read / prompt_total, 4) if prompt_total else None,
                "usage": range_usage.to_dict(),
            },
            "usage7": [day_row(offset) for offset in range(USAGE_DAYS - 1, -1, -1)],
            "heatmap": [day_row(offset) for offset in range(HEATMAP_DAYS - 1, -1, -1)],
            "composition": {**composition, "total": sum(composition.values())},
            "sessions": cards,
            "prices": self.price_info(),
        }
