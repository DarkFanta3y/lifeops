from __future__ import annotations

from dataclasses import dataclass, field
import re

import jieba

from lifeops.tools.base import ToolDefinition, ToolParams
from lifeops.utils.logging import get_logger

logger = get_logger(__name__)

MAX_LLM_TOOLS = 20
TOOL_NAME_MAX_LENGTH = 64
_TOOL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
_MATCH_TOKEN_PATTERN = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]+")
_CJK_PATTERN = re.compile(r"[\u4e00-\u9fff]+")
_MATCH_STOP_WORDS = {
    "please", "help", "tool", "tools", "use", "using",
    "this", "that", "the", "and", "for", "with", "from",
    "请", "帮我", "帮忙", "一下", "工具", "使用", "这个", "那个", "进行", "可以", "需要",
}

CORE_TOOL_ORDER = {
    "finish_task": -20,
    "exit_plan_mode": -15,
    "activate_skill": -10,
    "retrieve_knowledge": 0,
    "web_search": 1,
    "file_read": 2,
}
SIMPLE_WRITE_TOOL_ORDER = {
    "file_create": 10,
    "file_replace": 11,
    "file_append": 12,
}
LEGACY_OR_HIGH_RISK_ORDER = {
    "bash": 95,
}

INTENT_SERVER_KEYWORDS = {
    "github": {
        "github",
        "git hub",
        "repo",
        "repository",
        "仓库",
        "issue",
        "issues",
        "pull request",
        "pr",
        "profile",
    },
    "google": {"google", "gmail", "mail", "email", "邮件", "邮箱", "日历", "calendar", "drive"},
    "gmail": {"gmail", "mail", "email", "邮件", "邮箱"},
    "calendar": {"calendar", "日历", "schedule", "日程"},
    "drive": {"drive", "google drive", "文件云盘", "云盘"},
    "playwright": {"playwright", "browser", "浏览器", "网页自动化", "页面", "截图", "screenshot"},
    "browser": {"browser", "浏览器", "网页自动化", "页面", "截图", "screenshot"},
    "context7": {"context7", "docs", "documentation", "文档", "api reference", "库文档"},
    "memory": {"memory", "记忆", "remember", "回忆", "长期记忆"},
    "sequential_thinking": {"sequential", "thinking", "思考", "推理", "分步"},
    "sequential-thinking": {"sequential", "thinking", "思考", "推理", "分步"},
    "filesystem": {"filesystem", "file", "文件", "目录", "读取", "写入"},
    "12306": {"12306", "火车", "高铁", "动车", "车票", "铁路"},
}


@dataclass(frozen=True)
class ToolSelectionContext:
    user_input: str = ""
    active_skill_names: tuple[str, ...] = field(default_factory=tuple)
    active_skill_descriptions: tuple[str, ...] = field(default_factory=tuple)
    active_skill_allowed_tools: tuple[str, ...] = field(default_factory=tuple)
    used_tool_names: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class _ToolMatchContext:
    selection: ToolSelectionContext
    input_text: str
    skill_text: str
    input_tokens: set[str]
    skill_tokens: set[str]


def parameters_schema_from_model(parameters_model: type[ToolParams]) -> dict:
    json_schema = parameters_model.model_json_schema()
    parameters = {
        "type": "object",
        "properties": json_schema.get("properties", {}),
        "required": json_schema.get("required", []),
        "additionalProperties": json_schema.get("additionalProperties", False),
    }
    if "$defs" in json_schema:
        parameters["$defs"] = json_schema["$defs"]
    return parameters


def openai_tool_schema(tool_def: ToolDefinition) -> dict:
    validate_tool_name(tool_def.name)
    return {
        "type": "function",
        "function": {
            "name": tool_def.name,
            "description": tool_def.description,
            "parameters": parameters_schema_from_model(tool_def.parameters_model),
        },
    }


def validate_tool_name(name: str) -> str:
    """验证发送给 LLM 的 function name。"""
    if not isinstance(name, str) or not 1 <= len(name) <= TOOL_NAME_MAX_LENGTH:
        raise ValueError(f"工具名称不合法：长度必须为 1-{TOOL_NAME_MAX_LENGTH} 个字符")
    if _TOOL_NAME_PATTERN.fullmatch(name) is None:
        raise ValueError("工具名称不合法：只能包含字母、数字、下划线和短横线")
    return name


def tool_exposure_priority(tool_def: ToolDefinition) -> int:
    name = tool_def.name
    if name in CORE_TOOL_ORDER:
        return CORE_TOOL_ORDER[name]
    if name in SIMPLE_WRITE_TOOL_ORDER:
        return SIMPLE_WRITE_TOOL_ORDER[name]
    if name in LEGACY_OR_HIGH_RISK_ORDER:
        return LEGACY_OR_HIGH_RISK_ORDER[name]
    if tool_def.category == "mcp" and tool_def.read_only and tool_def.risk_level == "low":
        return 20
    if tool_def.read_only and tool_def.risk_level == "low":
        return 30
    if tool_def.category == "mcp" and tool_def.risk_level in {"low", "medium"}:
        return 40
    if tool_def.risk_level in {"low", "medium"} and not tool_def.requires_approval:
        return 50
    return 80


def select_llm_tools(
    tools: list[ToolDefinition],
    max_tools: int = MAX_LLM_TOOLS,
    context: ToolSelectionContext | None = None,
) -> list[ToolDefinition]:
    candidates = tools if context is None else _rank_contextual_tools(tools, context)
    if len(candidates) <= max_tools:
        if context is not None and len(candidates) != len(tools):
            logger.info(
                "LLM 工具列表已按上下文裁剪: original=%s selected=%s dropped_mcp=%s",
                len(tools),
                len(candidates),
                len(tools) - len(candidates),
            )
        return list(candidates)

    # Agent 已按上下文排好序；协议适配器无上下文调用时只对超限列表做静态裁剪。
    ranked = candidates if context is not None else sorted(candidates, key=tool_exposure_priority)
    selected = list(ranked[:max_tools])
    logger.info(
        "LLM 工具列表已裁剪: original=%s selected=%s dropped=%s",
        len(tools),
        len(selected),
        len(tools) - len(selected),
    )
    return selected


def _rank_contextual_tools(
    tools: list[ToolDefinition], context: ToolSelectionContext
) -> list[ToolDefinition]:
    input_text = _normalize_match_text(context.user_input)
    skill_text = _normalize_match_text(
        " ".join((*context.active_skill_names, *context.active_skill_descriptions))
    )
    match_context = _ToolMatchContext(
        selection=context,
        input_text=input_text,
        skill_text=skill_text,
        input_tokens=_meaningful_tokens(input_text),
        skill_tokens=_meaningful_tokens(skill_text),
    )
    ranked: list[tuple[tuple[int, int, int, int], ToolDefinition]] = []
    for index, tool in enumerate(tools):
        is_mcp = _is_mcp_tool(tool)
        score = _mcp_relevance_score(tool, match_context) if is_mcp else 0
        if is_mcp and score <= 0:
            continue
        priority = tool_exposure_priority(tool)
        if tool.name in CORE_TOOL_ORDER:
            key = (0, priority, 0, index)
        elif is_mcp and _matches_allowed_tool(tool, context.active_skill_allowed_tools):
            key = (1, -score, priority, index)
        elif is_mcp and (
            tool.name in context.used_tool_names
            or (tool.canonical_name or "") in context.used_tool_names
        ):
            key = (2, -score, priority, index)
        else:
            key = (3, priority, -score, index)
        ranked.append((key, tool))
    return [tool for _, tool in sorted(ranked, key=lambda item: item[0])]


def _is_mcp_tool(tool: ToolDefinition) -> bool:
    return tool.category == "mcp" or (tool.canonical_name or "").startswith("mcp.")


def _mcp_relevance_score(tool: ToolDefinition, context: _ToolMatchContext) -> int:
    score = 0
    selection = context.selection
    if _matches_allowed_tool(tool, selection.active_skill_allowed_tools):
        score += 100
    if (
        tool.name in selection.used_tool_names
        or (tool.canonical_name or "") in selection.used_tool_names
    ):
        score += 90

    server = _mcp_server_name(tool)
    tool_text = _normalize_match_text(
        " ".join(part for part in (tool.name, tool.canonical_name or "", tool.description) if part)
    )
    tool_tokens = _meaningful_tokens(tool_text)

    if server and _text_mentions_server(context.input_text, server):
        score += 60
    if server and _text_mentions_server(context.skill_text, server):
        score += 30
    if context.input_tokens & tool_tokens:
        score += 25
    if context.skill_tokens & tool_tokens:
        score += 15
    return score


def _matches_allowed_tool(tool: ToolDefinition, allowed_tools: tuple[str, ...]) -> bool:
    canonical_name = tool.canonical_name or ""
    for allowed in allowed_tools:
        allowed = allowed.strip()
        if not allowed:
            continue
        if allowed in {tool.name, canonical_name}:
            return True
        if allowed.startswith("mcp.") and allowed.endswith(".*"):
            prefix = allowed[:-1]
            if canonical_name.startswith(prefix):
                return True
    return False


def _mcp_server_name(tool: ToolDefinition) -> str | None:
    canonical_name = tool.canonical_name or ""
    if canonical_name.startswith("mcp."):
        parts = canonical_name.split(".")
        if len(parts) >= 2 and parts[1]:
            return parts[1].lower()
    name_parts = tool.name.split("_", 1)
    return name_parts[0].lower() if name_parts else None


def _text_mentions_server(text: str, server: str) -> bool:
    keywords = INTENT_SERVER_KEYWORDS.get(server, set()) | {server}
    for keyword in keywords:
        normalized = _normalize_match_text(keyword)
        if re.search(r"[a-z0-9]", normalized):
            # 使用 ASCII 边界，允许“查看PR状态”，同时避免 price 命中 pr。
            if re.search(r"(?<![a-z0-9])" + re.escape(normalized) + r"(?![a-z0-9])", text):
                return True
        elif normalized in text:
            return True
    return False


def _meaningful_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for part in _MATCH_TOKEN_PATTERN.findall(text.lower()):
        if _CJK_PATTERN.fullmatch(part):
            tokens.update(
                token for token in jieba.cut(part)
                if len(token) >= 2 and token not in _MATCH_STOP_WORDS
            )
        elif len(part) >= 3 and not part.isdigit() and part not in _MATCH_STOP_WORDS:
            tokens.add(part)
    return tokens


def _normalize_match_text(text: str) -> str:
    return " ".join(re.sub(r"[._-]+", " ", text.lower()).split())
