from __future__ import annotations

from enum import Enum


class PolicyAction(str, Enum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


DEFAULT_ALLOW_TOOLS = {
    "builtin.file_read",
    "builtin.retrieve_knowledge",
    "builtin.web_search",
}

DEFAULT_ASK_TOOLS = {
    "builtin.file_edit",
}

BASH_ALLOW_PREFIXES = (
    "pwd",
    "ls",
    "find",
    "rg",
    "sed",
    "git status",
    "git log",
    "uv run pytest",
    "uv run ruff check",
)

BASH_DENY_PATTERNS = (
    "rm -rf /",
    "git reset --hard",
    "curl",
    "wget",
    "/etc",
    "/usr",
    "/var",
)


def default_policy_summary(mode: str) -> dict[str, object]:
    return {
        "mode": mode,
        "allow_tools": sorted(DEFAULT_ALLOW_TOOLS),
        "ask_tools": sorted(DEFAULT_ASK_TOOLS) + ["mcp.*.*", "unknown high risk tools"],
        "bash_allow_prefixes": list(BASH_ALLOW_PREFIXES),
        "deny_bash_patterns": list(BASH_DENY_PATTERNS),
        "mcp_default_action": "ask",
    }
