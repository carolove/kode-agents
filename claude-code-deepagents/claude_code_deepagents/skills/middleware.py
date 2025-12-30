"""Middleware for loading and exposing agent skills to the system prompt.

This middleware implements Anthropic's "Agent Skills" pattern with progressive disclosure:
1. Parse YAML frontmatter from SKILL.md files at session start
2. Inject skills metadata (name + description) into system prompt
3. Agent reads full SKILL.md content when relevant to a task

Skills directory structure:
- User-level: ~/.deepagents/claude-code/skills/
- Project-level: {PROJECT_ROOT}/.deepagents/skills/
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, NotRequired, TypedDict, cast

from langchain.agents.middleware.types import (
    AgentMiddleware,
    AgentState,
    ModelRequest,
    ModelResponse,
)

from claude_code_deepagents.skills.load import SkillMetadata, list_skills

logger = logging.getLogger(__name__)

# Note: state and runtime params in before_agent are required by AgentMiddleware interface


class SkillsState(AgentState):
    """State for the skills middleware."""

    skills_metadata: NotRequired[list[SkillMetadata]]
    """List of loaded skill metadata (name, description, path)."""


class SkillsStateUpdate(TypedDict):
    """State update for the skills middleware."""

    skills_metadata: list[SkillMetadata]


# Skills System Prompt Template
SKILLS_SYSTEM_PROMPT = """

## Skills System

You have access to a skills library that provides specialized domain knowledge.

{skills_locations}

**Available Skills:**

{skills_list}

**How to Use Skills (Progressive Disclosure):**

Skills follow a **progressive disclosure** pattern - you see the summary above, 
but read full instructions when needed:

1. **Recognize when a skill applies**: Check if the user's task matches any skill's description
2. **Read the skill's full instructions**: Use read_file with the path shown above
3. **Follow the skill's instructions**: SKILL.md contains step-by-step workflows
4. **Access supporting files**: Skills may include scripts, configs, or reference docs

**When to Use Skills:**
- When the user's request matches a skill's domain (e.g., "research X" → web-research skill)
- When you need specialized knowledge or structured workflows
- When a skill provides proven patterns for complex tasks

**Example Workflow:**
User: "Can you research the latest developments in quantum computing?"
1. Check available skills above → See "web-research" skill
2. Read the skill using the path shown in the list
3. Follow the skill's research workflow
"""


class SkillsMiddleware(AgentMiddleware):
    """Middleware for loading and exposing agent skills.

    Implements Anthropic's agent skills pattern:
    - Loads skills metadata (name, description) from YAML frontmatter at session start
    - Injects skills list into system prompt for discoverability
    - Agent reads full SKILL.md content when relevant (progressive disclosure)
    """

    state_schema = SkillsState

    def __init__(
        self,
        *,
        user_skills_dir: str | Path | None = None,
        project_skills_dir: str | Path | None = None,
        assistant_id: str = "claude-code",
    ) -> None:
        """Initialize the skills middleware.

        Args:
            user_skills_dir: Path to the user-level skills directory.
            project_skills_dir: Path to the project-level skills directory.
            assistant_id: The agent identifier for path references in prompts.
        """
        if user_skills_dir is None:
            user_skills_dir = Path.home() / ".deepagents" / assistant_id / "skills"
        self.user_skills_dir = Path(user_skills_dir).expanduser()
        self.project_skills_dir = (
            Path(project_skills_dir).expanduser() if project_skills_dir else None
        )
        self.assistant_id = assistant_id
        self.user_skills_display = f"~/.deepagents/{assistant_id}/skills"
        self.system_prompt_template = SKILLS_SYSTEM_PROMPT

        logger.info(
            "[SkillsMiddleware] Initialized with user_skills_dir=%s, project_skills_dir=%s",
            self.user_skills_dir,
            self.project_skills_dir,
        )

    def _format_skills_locations(self) -> str:
        """Format skills locations for display in system prompt."""
        locations = [f"**User Skills**: `{self.user_skills_display}`"]
        if self.project_skills_dir:
            locations.append(
                f"**Project Skills**: `{self.project_skills_dir}` (overrides user skills)"
            )
        return "\n".join(locations)

    def _format_skills_list(self, skills: list[SkillMetadata]) -> str:
        """Format skills metadata for display in system prompt."""
        if not skills:
            return f"(No skills available yet. Create skills in {self.user_skills_display}/)"

        user_skills = [s for s in skills if s["source"] == "user"]
        project_skills = [s for s in skills if s["source"] == "project"]

        lines = []

        if user_skills:
            lines.append("**User Skills:**")
            for skill in user_skills:
                lines.append(f"- **{skill['name']}**: {skill['description']}")
                lines.append(f"  → Read `{skill['path']}` for full instructions")
            lines.append("")

        if project_skills:
            lines.append("**Project Skills:**")
            for skill in project_skills:
                lines.append(f"- **{skill['name']}**: {skill['description']}")
                lines.append(f"  → Read `{skill['path']}` for full instructions")

        return "\n".join(lines)

    def before_agent(
        self, state: SkillsState, runtime: Any
    ) -> SkillsStateUpdate | None:
        """Load skills metadata before agent execution."""
        logger.info("[SkillsMiddleware] before_agent: Loading skills metadata...")
        skills = list_skills(
            user_skills_dir=self.user_skills_dir,
            project_skills_dir=self.project_skills_dir,
        )
        skill_names = [s["name"] for s in skills]
        logger.info(
            "[SkillsMiddleware] before_agent: Loaded %d skills: %s",
            len(skills),
            skill_names,
        )
        return SkillsStateUpdate(skills_metadata=skills)

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        """Inject skills documentation into the system prompt."""
        skills_metadata = request.state.get("skills_metadata", [])
        skill_names = [s["name"] for s in skills_metadata]

        logger.debug(
            "[SkillsMiddleware] wrap_model_call: Injecting %d skills into system prompt: %s",
            len(skills_metadata),
            skill_names,
        )

        skills_locations = self._format_skills_locations()
        skills_list = self._format_skills_list(skills_metadata)

        skills_section = self.system_prompt_template.format(
            skills_locations=skills_locations,
            skills_list=skills_list,
        )

        if request.system_prompt:
            system_prompt = request.system_prompt + "\n\n" + skills_section
        else:
            system_prompt = skills_section

        logger.info(
            "[SkillsMiddleware] wrap_model_call: Skills section injected (%d chars)",
            len(skills_section),
        )

        return handler(request.override(system_prompt=system_prompt))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        """(async) Inject skills documentation into the system prompt."""
        state = cast("SkillsState", request.state)
        skills_metadata = state.get("skills_metadata", [])
        skill_names = [s["name"] for s in skills_metadata]

        logger.debug(
            "[SkillsMiddleware] awrap_model_call: Injecting %d skills into system prompt: %s",
            len(skills_metadata),
            skill_names,
        )

        skills_locations = self._format_skills_locations()
        skills_list = self._format_skills_list(skills_metadata)

        skills_section = self.system_prompt_template.format(
            skills_locations=skills_locations,
            skills_list=skills_list,
        )

        if request.system_prompt:
            system_prompt = request.system_prompt + "\n\n" + skills_section
        else:
            system_prompt = skills_section

        logger.info(
            "[SkillsMiddleware] awrap_model_call: Skills section injected (%d chars)",
            len(skills_section),
        )

        return await handler(request.override(system_prompt=system_prompt))

