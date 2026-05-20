from __future__ import annotations

from pydantic import ValidationError
import pytest

from lifeops.core.config import ToolPolicyConfig
from lifeops.runtime.policy import ToolPolicyContext, ToolPolicyEngine
from lifeops.runtime.policy_rules import PolicyAction, default_policy_summary
from lifeops.tools.base import ToolDefinition, ToolParams


class BashParams(ToolParams):
    command: str


def make_context(canonical_name: str) -> ToolPolicyContext:
    return ToolPolicyContext(
        conversation_id="conv",
        run_id="run",
        source="web",
        tool_name=canonical_name.split(".")[-1],
        canonical_name=canonical_name,
    )


def test_policy_allows_safe_read_and_safe_bash_prefixes():
    engine = ToolPolicyEngine(ToolPolicyConfig(mode="balanced"))
    bash_def = ToolDefinition(
        name="bash",
        description="bash",
        parameters_model=BashParams,
        canonical_name="builtin.bash",
        risk_level="high",
    )

    result = engine.evaluate(bash_def, {"command": "rg foo src"}, make_context("builtin.bash"))

    assert result.action == PolicyAction.ALLOW


def test_policy_denies_dangerous_bash_without_executing():
    engine = ToolPolicyEngine(ToolPolicyConfig(mode="balanced"))
    bash_def = ToolDefinition(
        name="bash",
        description="bash",
        parameters_model=BashParams,
        canonical_name="builtin.bash",
        risk_level="high",
    )

    result = engine.evaluate(bash_def, {"command": "git reset --hard"}, make_context("builtin.bash"))

    assert result.action == PolicyAction.DENY
    assert "拒绝" in result.reason


def test_policy_asks_for_file_edit_and_mcp_tools():
    engine = ToolPolicyEngine(ToolPolicyConfig(mode="balanced"))
    file_def = ToolDefinition(
        name="file_edit",
        description="edit",
        parameters_model=ToolParams,
        canonical_name="builtin.file_edit",
        risk_level="high",
    )
    mcp_def = ToolDefinition(
        name="github_get_me",
        description="mcp",
        parameters_model=ToolParams,
        canonical_name="mcp.github.get_me",
    )

    assert engine.evaluate(file_def, {}, make_context("builtin.file_edit")).action == PolicyAction.ASK
    assert engine.evaluate(mcp_def, {}, make_context("mcp.github.get_me")).action == PolicyAction.ASK


def test_policy_modes_and_config_validation():
    high_def = ToolDefinition(
        name="custom",
        description="custom",
        parameters_model=ToolParams,
        canonical_name="custom.unknown",
        risk_level="high",
    )

    off = ToolPolicyEngine(ToolPolicyConfig(mode="off"))
    strict = ToolPolicyEngine(ToolPolicyConfig(mode="strict"))

    assert off.evaluate(high_def, {}, make_context("custom.unknown")).action == PolicyAction.ALLOW
    assert strict.evaluate(high_def, {}, make_context("custom.unknown")).action == PolicyAction.DENY
    with pytest.raises(ValidationError):
        ToolPolicyConfig(mode="unsafe")


def test_default_policy_summary_contains_public_rules_only():
    summary = default_policy_summary("balanced")
    assert summary["mode"] == "balanced"
    assert "builtin.file_read" in summary["allow_tools"]
    assert "git reset --hard" in summary["deny_bash_patterns"]
    assert "api_key" not in str(summary).lower()
