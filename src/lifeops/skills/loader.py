from __future__ import annotations

from pathlib import Path
from typing import Any

from lifeops.skills.types import SkillCatalog, SkillMetadata, SkillSource
from lifeops.utils.logging import get_logger

logger = get_logger(__name__)

KNOWN_FRONTMATTER_KEYS = {
    "name",
    "description",
    "metadata",
    "allowed-tools",
    "dependencies",
    "policy",
}


class SkillLoader:
    def __init__(self, project_dir: str | Path, user_dir: str | Path):
        self.project_dir = Path(project_dir).expanduser()
        self.user_dir = Path(user_dir).expanduser()

    def discover(self) -> SkillCatalog:
        skills: dict[str, SkillMetadata] = {}
        warnings: list[str] = []

        for root, source in (
            (self.project_dir, SkillSource.PROJECT),
            (self.user_dir, SkillSource.USER),
        ):
            for warning, metadata in self._discover_root(root, source):
                if warning:
                    warnings.append(warning)
                    logger.warning(warning)
                    continue
                if metadata is None:
                    continue
                if metadata.name in skills:
                    warnings.append(
                        f"跳过重复 Skill '{metadata.name}' ({metadata.path})，"
                        f"已使用 {skills[metadata.name].source.value} 版本"
                    )
                    continue
                skills[metadata.name] = metadata

        return SkillCatalog(skills=skills, warnings=warnings)

    def _discover_root(
        self, root: Path, source: SkillSource
    ) -> list[tuple[str | None, SkillMetadata | None]]:
        if not root.exists():
            return []

        results: list[tuple[str | None, SkillMetadata | None]] = []
        for child in sorted(path for path in root.iterdir() if path.is_dir()):
            skill_file = child / "SKILL.md"
            if not skill_file.exists():
                results.append((f"跳过 Skill 目录 {child}: 缺少 SKILL.md", None))
                continue
            try:
                results.append((None, self._load_metadata(skill_file, child, source)))
            except ValueError as exc:
                results.append((f"跳过 Skill {skill_file}: {exc}", None))
            except OSError as exc:
                results.append((f"跳过 Skill {skill_file}: 读取失败: {exc}", None))
        return results

    def _load_metadata(
        self, skill_file: Path, directory: Path, source: SkillSource
    ) -> SkillMetadata:
        content = skill_file.read_text(encoding="utf-8")
        frontmatter = self._extract_frontmatter(content)

        name = frontmatter.get("name")
        description = frontmatter.get("description")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("缺少必填字段 name")
        if not isinstance(description, str) or not description.strip():
            raise ValueError("缺少必填字段 description")

        metadata = frontmatter.get("metadata")
        short_description = None
        if isinstance(metadata, dict):
            short_description_value = metadata.get("short-description")
            if isinstance(short_description_value, str):
                short_description = short_description_value

        policy = frontmatter.get("policy")
        allow_implicit_invocation = True
        if isinstance(policy, dict) and isinstance(policy.get("allow_implicit_invocation"), bool):
            allow_implicit_invocation = policy["allow_implicit_invocation"]

        return SkillMetadata(
            name=name.strip(),
            description=description.strip(),
            path=skill_file,
            directory=directory,
            source=source,
            raw_frontmatter=frontmatter,
            short_description=short_description,
            allowed_tools=_string_list(frontmatter.get("allowed-tools")),
            dependencies=_string_list(frontmatter.get("dependencies")),
            allow_implicit_invocation=allow_implicit_invocation,
            extra={
                key: value
                for key, value in frontmatter.items()
                if key not in KNOWN_FRONTMATTER_KEYS
            },
        )

    def _extract_frontmatter(self, content: str) -> dict[str, Any]:
        lines = content.splitlines()
        if not lines or lines[0].strip() != "---":
            raise ValueError("缺少 YAML frontmatter")

        end_index = None
        for index, line in enumerate(lines[1:], start=1):
            if line.strip() == "---":
                end_index = index
                break
        if end_index is None:
            raise ValueError("frontmatter 未闭合")

        return _parse_yaml_subset(lines[1:end_index])


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _parse_yaml_subset(lines: list[str]) -> dict[str, Any]:
    root: dict[str, Any] = {}
    stack: list[tuple[int, Any]] = [(-1, root)]

    for line_number, raw_line in enumerate(lines, start=2):
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue

        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]

        if line.startswith("- "):
            if not isinstance(parent, list):
                raise ValueError(f"第 {line_number} 行列表缩进无效")
            item = _parse_list_item(line[2:], line_number)
            parent.append(item)
            if isinstance(item, dict):
                stack.append((indent, item))
            continue

        if ":" not in line:
            raise ValueError(f"第 {line_number} 行格式无效")
        key, raw_value = line.split(":", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        if not key:
            raise ValueError(f"第 {line_number} 行缺少键名")
        if not isinstance(parent, dict):
            raise ValueError(f"第 {line_number} 行映射缩进无效")

        if raw_value == "":
            container: dict[str, Any] | list[Any]
            next_line = _next_content_line(lines, line_number - 1)
            container = [] if next_line and next_line.strip().startswith("- ") else {}
            parent[key] = container
            stack.append((indent, container))
        else:
            parent[key] = _parse_scalar(raw_value, line_number)

    return root


def _next_content_line(lines: list[str], current_index: int) -> str | None:
    for next_line in lines[current_index:]:
        if next_line.strip() and not next_line.lstrip().startswith("#"):
            return next_line
    return None


def _parse_list_item(raw_value: str, line_number: int) -> Any:
    if ":" in raw_value and not raw_value.startswith(("'", '"')):
        key, value = raw_value.split(":", 1)
        return {key.strip(): _parse_scalar(value.strip(), line_number)}
    return _parse_scalar(raw_value, line_number)


def _parse_scalar(value: str, line_number: int) -> Any:
    if value in {"true", "True"}:
        return True
    if value in {"false", "False"}:
        return False
    if value in {"null", "Null", "~"}:
        return None
    if value.startswith("[") or value.startswith("{"):
        raise ValueError(f"第 {line_number} 行包含不支持或无效的内联 YAML")
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]
    return value
