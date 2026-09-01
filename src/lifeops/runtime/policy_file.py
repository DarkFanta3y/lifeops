from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from lifeops.utils.logging import get_logger

logger = get_logger(__name__)

POLICY_FILE_VERSION = 1


@dataclass
class UserPolicyOverrides:
    allow_tools: set[str] = field(default_factory=set)
    bash_allow_prefixes: list[str] = field(default_factory=list)
    deny_tools: set[str] = field(default_factory=set)


class PolicyFileStore:
    """读写用户级工具策略覆盖文件（.lifeops/tool-policy.json）。

    文件由审批闭环的“总是允许”决策写入；格式带版本号，损坏或缺失时返回空覆盖。
    """

    def __init__(self, path: str) -> None:
        self.path = Path(path)

    def load(self) -> UserPolicyOverrides:
        if not self.path.exists():
            return UserPolicyOverrides()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            logger.warning(f"读取工具策略文件失败，忽略用户覆盖: {error}")
            return UserPolicyOverrides()
        if not isinstance(data, dict):
            return UserPolicyOverrides()
        return UserPolicyOverrides(
            allow_tools={str(item) for item in data.get("allow_tools", [])},
            bash_allow_prefixes=[str(item) for item in data.get("bash_allow_prefixes", [])],
            deny_tools={str(item) for item in data.get("deny_tools", [])},
        )

    def _write(self, overrides: UserPolicyOverrides) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": POLICY_FILE_VERSION,
            "allow_tools": sorted(overrides.allow_tools),
            "bash_allow_prefixes": sorted(set(overrides.bash_allow_prefixes)),
            "deny_tools": sorted(overrides.deny_tools),
        }
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    def add_tool_allow(self, canonical_name: str) -> None:
        overrides = self.load()
        if canonical_name in overrides.allow_tools:
            return
        overrides.allow_tools.add(canonical_name)
        self._write(overrides)

    def add_bash_allow_prefix(self, command: str) -> None:
        prefix = " ".join(command.split()[:2])
        if not prefix:
            return
        overrides = self.load()
        if prefix in overrides.bash_allow_prefixes:
            return
        overrides.bash_allow_prefixes.append(prefix)
        self._write(overrides)
