"""Skill loader for parsing and loading agent skills from SKILL.md files.

This module implements Anthropic's agent skills pattern with YAML frontmatter parsing.
Each skill is a directory containing a SKILL.md file with:
- YAML frontmatter (name, description required)
- Markdown instructions for the agent
- Optional supporting files (scripts, configs, etc.)

Example SKILL.md structure:
```markdown
---
name: web-research
description: Structured approach to conducting thorough web research
---

# Web Research Skill

## When to Use
- User asks you to research a topic
...
```
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import NotRequired, TypedDict

import yaml

logger = logging.getLogger(__name__)

# Maximum size for SKILL.md files (10MB)
MAX_SKILL_FILE_SIZE = 10 * 1024 * 1024

# Agent Skills spec constraints
MAX_SKILL_NAME_LENGTH = 64
MAX_SKILL_DESCRIPTION_LENGTH = 1024


class SkillMetadata(TypedDict):
    """Metadata for a skill per Agent Skills spec."""

    name: str
    """Name of the skill (max 64 chars, lowercase alphanumeric and hyphens)."""

    description: str
    """Description of what the skill does (max 1024 chars)."""

    path: str
    """Path to the SKILL.md file."""

    source: str
    """Source of the skill ('user' or 'project')."""

    body: NotRequired[str]
    """The markdown body of the skill (loaded on demand)."""

    # Optional fields per Agent Skills spec
    license: NotRequired[str | None]
    compatibility: NotRequired[str | None]
    metadata: NotRequired[dict[str, str] | None]
    allowed_tools: NotRequired[str | None]


def _is_safe_path(path: Path, base_dir: Path) -> bool:
    """Check if a path is safely contained within base_dir."""
    try:
        resolved_path = path.resolve()
        resolved_base = base_dir.resolve()
        resolved_path.relative_to(resolved_base)
        return True
    except ValueError:
        return False
    except (OSError, RuntimeError):
        return False


def _validate_skill_name(name: str, directory_name: str) -> tuple[bool, str]:
    """Validate skill name per Agent Skills spec."""
    if not name:
        return False, "name is required"
    if len(name) > MAX_SKILL_NAME_LENGTH:
        return False, "name exceeds 64 characters"
    if not re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", name):
        return False, "name must be lowercase alphanumeric with single hyphens only"
    if name != directory_name:
        return False, f"name '{name}' must match directory name '{directory_name}'"
    return True, ""


def _parse_skill_metadata(skill_md_path: Path, source: str) -> SkillMetadata | None:
    """Parse YAML frontmatter from a SKILL.md file."""
    try:
        file_size = skill_md_path.stat().st_size
        if file_size > MAX_SKILL_FILE_SIZE:
            logger.warning("Skipping %s: file too large (%d bytes)", skill_md_path, file_size)
            return None

        content = skill_md_path.read_text(encoding="utf-8")

        # Match YAML frontmatter between --- delimiters
        frontmatter_pattern = r"^---\s*\n(.*?)\n---\s*\n(.*)$"
        match = re.match(frontmatter_pattern, content, re.DOTALL)

        if not match:
            logger.warning("Skipping %s: no valid YAML frontmatter found", skill_md_path)
            return None

        frontmatter_str = match.group(1)
        body = match.group(2).strip()

        try:
            frontmatter_data = yaml.safe_load(frontmatter_str)
        except yaml.YAMLError as e:
            logger.warning("Invalid YAML in %s: %s", skill_md_path, e)
            return None

        if not isinstance(frontmatter_data, dict):
            logger.warning("Skipping %s: frontmatter is not a mapping", skill_md_path)
            return None

        name = frontmatter_data.get("name")
        description = frontmatter_data.get("description")

        if not name or not description:
            logger.warning("Skipping %s: missing required 'name' or 'description'", skill_md_path)
            return None

        # Validate name format (warn but still load)
        directory_name = skill_md_path.parent.name
        is_valid, error = _validate_skill_name(str(name), directory_name)
        if not is_valid:
            logger.warning("Skill '%s' in %s: %s", name, skill_md_path, error)

        description_str = str(description)
        if len(description_str) > MAX_SKILL_DESCRIPTION_LENGTH:
            description_str = description_str[:MAX_SKILL_DESCRIPTION_LENGTH]

        return SkillMetadata(
            name=str(name),
            description=description_str,
            path=str(skill_md_path),
            source=source,
            body=body,
            license=frontmatter_data.get("license"),
            compatibility=frontmatter_data.get("compatibility"),
            metadata=frontmatter_data.get("metadata"),
            allowed_tools=frontmatter_data.get("allowed-tools"),
        )
    except (OSError, UnicodeDecodeError) as e:
        logger.warning("Error reading %s: %s", skill_md_path, e)
        return None


def _list_skills(skills_dir: Path, source: str) -> list[SkillMetadata]:
    """List all skills from a single skills directory."""
    skills_dir = skills_dir.expanduser()
    if not skills_dir.exists():
        logger.debug("[SkillLoader] Skills directory does not exist: %s", skills_dir)
        return []

    try:
        resolved_base = skills_dir.resolve()
    except (OSError, RuntimeError):
        logger.warning("[SkillLoader] Cannot resolve skills directory: %s", skills_dir)
        return []

    logger.debug("[SkillLoader] Scanning skills directory: %s (source=%s)", skills_dir, source)
    skills: list[SkillMetadata] = []

    for skill_dir in skills_dir.iterdir():
        if not _is_safe_path(skill_dir, resolved_base):
            continue
        if not skill_dir.is_dir():
            continue

        skill_md_path = skill_dir / "SKILL.md"
        if not skill_md_path.exists():
            logger.debug("[SkillLoader] No SKILL.md in %s, skipping", skill_dir.name)
            continue

        if not _is_safe_path(skill_md_path, resolved_base):
            continue

        metadata = _parse_skill_metadata(skill_md_path, source=source)
        if metadata:
            logger.info(
                "[SkillLoader] Loaded skill '%s' from %s (source=%s)",
                metadata["name"],
                skill_md_path,
                source,
            )
            skills.append(metadata)

    return skills


def list_skills(
    *, user_skills_dir: Path | None = None, project_skills_dir: Path | None = None
) -> list[SkillMetadata]:
    """List skills from user and/or project directories.

    Project skills override user skills with the same name.

    Args:
        user_skills_dir: Path to the user-level skills directory.
        project_skills_dir: Path to the project-level skills directory.

    Returns:
        Merged list of skill metadata from both sources.
    """
    logger.info("[SkillLoader] list_skills called with user_dir=%s, project_dir=%s",
                user_skills_dir, project_skills_dir)

    all_skills: dict[str, SkillMetadata] = {}

    if user_skills_dir:
        user_skills = _list_skills(user_skills_dir, source="user")
        logger.info("[SkillLoader] Found %d user skills", len(user_skills))
        for skill in user_skills:
            all_skills[skill["name"]] = skill

    if project_skills_dir:
        project_skills = _list_skills(project_skills_dir, source="project")
        logger.info("[SkillLoader] Found %d project skills", len(project_skills))
        for skill in project_skills:
            if skill["name"] in all_skills:
                logger.info(
                    "[SkillLoader] Project skill '%s' overrides user skill",
                    skill["name"],
                )
            all_skills[skill["name"]] = skill

    logger.info(
        "[SkillLoader] Total skills loaded: %d (%s)",
        len(all_skills),
        list(all_skills.keys()),
    )
    return list(all_skills.values())


class SkillLoader:
    """Loads and manages skills from SKILL.md files.

    Supports progressive disclosure:
    - Layer 1: Metadata only (name + description) loaded at startup
    - Layer 2: Full SKILL.md body loaded on demand
    - Layer 3: Supporting resources (scripts, configs) referenced in skill
    """

    def __init__(
        self,
        user_skills_dir: Path | None = None,
        project_skills_dir: Path | None = None,
    ):
        """Initialize the skill loader.

        Args:
            user_skills_dir: Path to user-level skills directory.
            project_skills_dir: Path to project-level skills directory.
        """
        logger.info(
            "[SkillLoader] Initializing with user_dir=%s, project_dir=%s",
            user_skills_dir,
            project_skills_dir,
        )
        self.user_skills_dir = user_skills_dir
        self.project_skills_dir = project_skills_dir
        self.skills: dict[str, SkillMetadata] = {}
        self.load_skills()

    def load_skills(self) -> None:
        """Scan skills directories and load all valid SKILL.md files."""
        logger.info("[SkillLoader] load_skills: Scanning for skills...")
        skills_list = list_skills(
            user_skills_dir=self.user_skills_dir,
            project_skills_dir=self.project_skills_dir,
        )
        self.skills = {skill["name"]: skill for skill in skills_list}
        logger.info(
            "[SkillLoader] load_skills: Loaded %d skills into cache: %s",
            len(self.skills),
            list(self.skills.keys()),
        )

    def get_descriptions(self) -> str:
        """Generate skill descriptions for system prompt (Layer 1)."""
        if not self.skills:
            logger.debug("[SkillLoader] get_descriptions: No skills available")
            return "(no skills available)"

        logger.debug(
            "[SkillLoader] get_descriptions: Generating descriptions for %d skills",
            len(self.skills),
        )
        return "\n".join(
            f"- {name}: {skill['description']}"
            for name, skill in self.skills.items()
        )

    def get_skill_content(self, name: str) -> str | None:
        """Get full skill content for injection (Layer 2 + Layer 3 hints)."""
        if name not in self.skills:
            logger.warning("[SkillLoader] get_skill_content: Skill '%s' not found", name)
            return None

        logger.info("[SkillLoader] get_skill_content: Loading full content for skill '%s'", name)
        skill = self.skills[name]
        body = skill.get("body", "")
        content = f"# Skill: {skill['name']}\n\n{body}"

        # List available resources (Layer 3 hints)
        skill_dir = Path(skill["path"]).parent
        resources = []
        for folder, label in [
            ("scripts", "Scripts"),
            ("references", "References"),
            ("assets", "Assets"),
        ]:
            folder_path = skill_dir / folder
            if folder_path.exists():
                files = list(folder_path.glob("*"))
                if files:
                    resources.append(f"{label}: {', '.join(f.name for f in files)}")
                    logger.debug(
                        "[SkillLoader] get_skill_content: Found %d %s files in %s",
                        len(files),
                        label.lower(),
                        folder_path,
                    )

        if resources:
            content += f"\n\n**Available resources in {skill_dir}:**\n"
            content += "\n".join(f"- {r}" for r in resources)

        logger.info(
            "[SkillLoader] get_skill_content: Skill '%s' content loaded (%d chars)",
            name,
            len(content),
        )
        return content

    def list_skills(self) -> list[str]:
        """Return list of available skill names."""
        skill_names = list(self.skills.keys())
        logger.debug("[SkillLoader] list_skills: Returning %d skills: %s", len(skill_names), skill_names)
        return skill_names

