from __future__ import annotations

from pathlib import Path

from lifeops.core.context_manager import ContextLayer, ContextManager
from lifeops.skills.loader import SkillLoader
from lifeops.skills.types import SkillCatalog, SkillDefinition, SkillMetadata
from lifeops.utils.logging import get_logger

logger = get_logger(__name__)


class SkillManager:
    def __init__(
        self,
        context: ContextManager,
        project_dir: str | Path,
        user_dir: str | Path,
        max_active: int = 3,
    ):
        self.context = context
        self.loader = SkillLoader(project_dir=project_dir, user_dir=user_dir)
        self.max_active = max_active
        self.catalog = SkillCatalog(skills={})
        self.active_skill_names: list[str] = []

    @property
    def skills(self) -> dict[str, SkillMetadata]:
        return self.catalog.skills

    def discover(self) -> SkillCatalog:
        self.catalog = self.loader.discover()
        self.inject_catalog()
        logger.info(f"Skills: 已预加载 {len(self.catalog.skills)} 个 Skill")
        return self.catalog

    def inject_catalog(self) -> None:
        summary = self.catalog_summary()
        if not summary:
            self.context.remove_content("skills_catalog")
            return
        self.context.add_content("skills_catalog", summary, ContextLayer.L1)

    def catalog_summary(self) -> str:
        if not self.catalog.skills:
            return ""
        lines = ["可用 Skills（仅目录摘要；完整正文会在触发后进入 L2）:"]
        lines.extend(
            f"- {skill.name} - {skill.description}" for skill in self.catalog.skills.values()
        )
        return "\n".join(lines)

    def activate(self, name: str) -> SkillDefinition | None:
        metadata = self.catalog.skills.get(name)
        if metadata is None:
            logger.warning(f"尝试激活未知 Skill: {name}")
            return None

        content = metadata.path.read_text(encoding="utf-8")
        definition = SkillDefinition(metadata=metadata, content=content)
        if name in self.active_skill_names:
            self.active_skill_names = [
                active_name for active_name in self.active_skill_names if active_name != name
            ]
        self.active_skill_names.append(name)
        self._trim_active_skills()

        self.context.add_content(
            f"skill:{name}",
            self._format_skill_context(definition),
            ContextLayer.L2,
        )
        return definition

    def clear_active(self) -> None:
        for name in list(self.active_skill_names):
            self.context.remove_content(f"skill:{name}")
        self.active_skill_names.clear()

    def _trim_active_skills(self) -> None:
        while len(self.active_skill_names) > self.max_active:
            removed_name = self.active_skill_names.pop(0)
            self.context.remove_content(f"skill:{removed_name}")

    def _format_skill_context(self, definition: SkillDefinition) -> str:
        name = definition.metadata.name
        return f"已激活 Skill: {name}\n\n{definition.content}"
