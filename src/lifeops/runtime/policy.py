from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from lifeops.core.config import ToolPolicyConfig
from lifeops.runtime.policy_rules import (
    BASH_ALLOW_PREFIXES,
    BASH_DENY_PATTERNS,
    DEFAULT_ALLOW_TOOLS,
    DEFAULT_ASK_TOOLS,
    PolicyAction,
)
from lifeops.tools.base import ToolDefinition


@dataclass(frozen=True)
class ToolPolicyContext:
    conversation_id: str
    run_id: str | None
    source: str
    tool_name: str
    canonical_name: str


@dataclass(frozen=True)
class ToolPolicyResult:
    action: PolicyAction
    reason: str
    risk_level: str
    matched_rule: str


class ToolPolicyEngine:
    def __init__(self, config: ToolPolicyConfig) -> None:
        self.config = config

    def evaluate(
        self,
        tool_definition: ToolDefinition | None,
        params: dict[str, Any],
        context: ToolPolicyContext,
    ) -> ToolPolicyResult:
        if self.config.mode == "off":
            return self._result(PolicyAction.ALLOW, "工具策略已关闭。", "low", "mode:off")

        canonical_name = context.canonical_name
        risk_level = tool_definition.risk_level if tool_definition is not None else "high"

        if canonical_name == "builtin.bash":
            return self._evaluate_bash(params, risk_level)
        if canonical_name in DEFAULT_ALLOW_TOOLS:
            return self._result(PolicyAction.ALLOW, "只读工具允许执行。", risk_level, "default_allow")
        if canonical_name in DEFAULT_ASK_TOOLS:
            return self._result(
                PolicyAction.ASK, "工具需要人工授权，当前未执行。", risk_level, "default_ask"
            )
        if canonical_name.startswith("mcp."):
            return self._result(
                PolicyAction.ASK, "MCP 工具默认需要人工授权，当前未执行。", risk_level, "mcp_default"
            )
        if self.config.mode == "strict":
            return self._result(
                PolicyAction.DENY, "严格模式拒绝未知工具。", risk_level, "strict_unknown"
            )
        if risk_level == "high" or getattr(tool_definition, "requires_approval", False):
            return self._result(
                PolicyAction.ASK, "高风险工具需要人工授权，当前未执行。", risk_level, "high_risk"
            )
        return self._result(PolicyAction.ALLOW, "默认允许低/中风险工具。", risk_level, "default")

    def _evaluate_bash(self, params: dict[str, Any], risk_level: str) -> ToolPolicyResult:
        command = str(params.get("command") or "").strip()
        if not command:
            return self._result(PolicyAction.DENY, "拒绝执行空 bash 命令。", risk_level, "empty_bash")
        lowered = command.lower()
        if any(pattern in lowered for pattern in BASH_DENY_PATTERNS):
            return self._result(
                PolicyAction.DENY,
                "拒绝执行危险 bash 命令。",
                risk_level,
                "bash_deny_pattern",
            )
        if any(lowered == prefix or lowered.startswith(prefix + " ") for prefix in BASH_ALLOW_PREFIXES):
            return self._result(PolicyAction.ALLOW, "bash 命令匹配允许前缀。", risk_level, "bash_allow")
        return self._result(
            PolicyAction.ASK, "bash 命令需要人工授权，当前未执行。", risk_level, "bash_default_ask"
        )

    def _result(
        self, action: PolicyAction, reason: str, risk_level: str, matched_rule: str
    ) -> ToolPolicyResult:
        return ToolPolicyResult(
            action=action,
            reason=reason,
            risk_level=risk_level,
            matched_rule=matched_rule,
        )
