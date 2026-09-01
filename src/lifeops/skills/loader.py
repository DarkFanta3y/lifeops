from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from lifeops.skills.types import SkillCatalog, SkillMetadata, SkillSource
from lifeops.utils.logging import get_logger

logger = get_logger(__name__)

STANDARD_FRONTMATTER_KEYS = {
    "name",
    "description",
    "license",
    "compatibility",
    "metadata",
    "allowed-tools",
}
SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


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
                metadata, metadata_warnings = self._load_metadata(skill_file, child, source)
                results.extend((warning, None) for warning in metadata_warnings)
                results.append((None, metadata))
            except (TypeError, ValueError, yaml.YAMLError) as exc:
                results.append((f"跳过 Skill {skill_file}: {exc}", None))
            except OSError as exc:
                results.append((f"跳过 Skill {skill_file}: 读取失败: {exc}", None))
        return results

    def _load_metadata(
        self, skill_file: Path, directory: Path, source: SkillSource
    ) -> tuple[SkillMetadata, list[str]]:
        content = skill_file.read_text(encoding="utf-8")
        frontmatter = self._extract_frontmatter(content)

        name = _required_string(frontmatter, "name")
        description = _required_string(frontmatter, "description")
        if len(name) > 64 or not SKILL_NAME_PATTERN.fullmatch(name):
            raise ValueError("name 必须是 1–64 个小写字母、数字和单连字符组成的标准名称")
        if name != directory.name:
            raise ValueError("name 必须与 Skill 父目录名一致")
        if len(description) > 1024:
            raise ValueError("description 长度不能超过 1024 个字符")

        license_value = _optional_string(frontmatter, "license")
        compatibility = _optional_string(frontmatter, "compatibility")
        if compatibility is not None and len(compatibility) > 500:
            raise ValueError("compatibility 长度不能超过 500 个字符")

        standard_metadata = frontmatter.get("metadata", {})
        if not isinstance(standard_metadata, dict):
            raise ValueError("metadata 必须是 YAML mapping")
        lifeops_metadata = standard_metadata.get("lifeops", {})
        if not isinstance(lifeops_metadata, dict):
            raise ValueError("metadata.lifeops 必须是 YAML mapping")

        allowed_tools = _string_list(frontmatter.get("allowed-tools"), "allowed-tools")
        dependencies = _string_list(lifeops_metadata.get("dependencies"), "metadata.lifeops.dependencies")
        allow_implicit_invocation = lifeops_metadata.get("allow-implicit-invocation", True)
        if not isinstance(allow_implicit_invocation, bool):
            raise ValueError("metadata.lifeops.allow-implicit-invocation 必须是布尔值")

        extra = {
            key: value
            for key, value in frontmatter.items()
            if key not in STANDARD_FRONTMATTER_KEYS
        }
        unknown_keys = sorted(extra, key=str)
        metadata = SkillMetadata(
            name=name,
            description=description.strip(),
            path=skill_file,
            directory=directory,
            source=source,
            raw_frontmatter=frontmatter,
            license=license_value,
            compatibility=compatibility,
            metadata=standard_metadata,
            short_description=_optional_string(standard_metadata, "short-description"),
            allowed_tools=allowed_tools,
            dependencies=dependencies,
            allow_implicit_invocation=allow_implicit_invocation,
            extra=extra,
        )
        warnings = [
            f"Skill {skill_file} 包含未知顶层字段: {', '.join(unknown_keys)}"
        ] if unknown_keys else []
        return metadata, warnings

    def _extract_frontmatter(self, content: str) -> dict[str, Any]:
        lines = content.splitlines()
        if not lines or lines[0].strip() != "---":
            raise ValueError("缺少 YAML frontmatter")

        try:
            end_index = next(index for index, line in enumerate(lines[1:], 1) if line.strip() == "---")
        except StopIteration as exc:
            raise ValueError("frontmatter 未闭合") from exc

        parsed = yaml.safe_load("\n".join(lines[1:end_index]))
        if not isinstance(parsed, dict):
            raise ValueError("frontmatter 必须是 YAML mapping")
        return parsed


def _required_string(mapping: dict[str, Any], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"缺少必填字段 {key}")
    return value.strip()


def _optional_string(mapping: dict[str, Any], key: str) -> str | None:
    value = mapping.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} 必须是字符串")
    return value.strip()


def _string_list(value: Any, field_name: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return value.split()
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return value
    raise ValueError(f"{field_name} 必须是空格分隔字符串或字符串列表")
