from pathlib import Path

from lifeops.skills.loader import SkillLoader
from lifeops.skills.types import SkillSource


def write_skill(root: Path, folder: str, content: str) -> Path:
    skill_dir = root / folder
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(content, encoding="utf-8")
    return skill_file


def test_loader_discovers_project_and_user_skills(tmp_path: Path):
    project_dir = tmp_path / "project"
    user_dir = tmp_path / "user"
    write_skill(
        project_dir,
        "weekly-review",
        """---
name: weekly-review
description: 整理本周记录。
---

# Weekly Review
""",
    )
    write_skill(
        user_dir,
        "meal-plan",
        """---
name: meal-plan
description: 规划饮食。
---

# Meal Plan
""",
    )

    catalog = SkillLoader(project_dir=project_dir, user_dir=user_dir).discover()

    assert set(catalog.skills) == {"weekly-review", "meal-plan"}
    assert catalog.skills["weekly-review"].source == SkillSource.PROJECT
    assert catalog.skills["meal-plan"].source == SkillSource.USER
    assert catalog.warnings == []


def test_loader_project_skill_overrides_user_skill_with_same_name(tmp_path: Path):
    project_dir = tmp_path / "project"
    user_dir = tmp_path / "user"
    write_skill(
        user_dir,
        "weekly-review-user",
        """---
name: weekly-review
description: 用户版本。
---

# User
""",
    )
    project_file = write_skill(
        project_dir,
        "weekly-review-project",
        """---
name: weekly-review
description: 项目版本。
---

# Project
""",
    )

    catalog = SkillLoader(project_dir=project_dir, user_dir=user_dir).discover()

    assert list(catalog.skills) == ["weekly-review"]
    assert catalog.skills["weekly-review"].path == project_file
    assert catalog.skills["weekly-review"].description == "项目版本。"
    assert any("重复" in warning for warning in catalog.warnings)


def test_loader_skips_invalid_yaml_missing_required_fields_and_missing_skill_md(
    tmp_path: Path,
):
    project_dir = tmp_path / "project"
    (project_dir / "missing").mkdir(parents=True)
    write_skill(
        project_dir,
        "invalid-yaml",
        """---
name: [broken
description: 坏 YAML。
---

# Invalid
""",
    )
    write_skill(
        project_dir,
        "missing-description",
        """---
name: missing-description
---

# Missing
""",
    )

    catalog = SkillLoader(project_dir=project_dir, user_dir=tmp_path / "none").discover()

    assert catalog.skills == {}
    assert len(catalog.warnings) == 3


def test_loader_parses_and_preserves_compatible_optional_fields(tmp_path: Path):
    project_dir = tmp_path / "project"
    skill_file = write_skill(
        project_dir,
        "draft-email",
        """---
name: draft-email
description: 起草邮件。
metadata:
  short-description: 邮件草稿
allowed-tools:
  - file_read
  - bash
dependencies:
  - google-workspace
policy:
  allow_implicit_invocation: false
lifeops:
  workflow:
    - step: draft
---

# Draft Email
""",
    )

    catalog = SkillLoader(project_dir=project_dir, user_dir=tmp_path / "none").discover()
    skill = catalog.skills["draft-email"]

    assert skill.path == skill_file
    assert skill.short_description == "邮件草稿"
    assert skill.allowed_tools == ["file_read", "bash"]
    assert skill.dependencies == ["google-workspace"]
    assert skill.allow_implicit_invocation is False
    assert skill.extra["lifeops"] == {"workflow": [{"step": "draft"}]}
