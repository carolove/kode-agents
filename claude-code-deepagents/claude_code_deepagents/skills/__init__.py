"""Skills module for claude-code-deepagents.

This module provides skill loading and middleware integration for the agent.
Skills are domain knowledge files (SKILL.md) that teach the agent how to
handle specific types of tasks.

Public API:
- SkillLoader: Load and manage skills from SKILL.md files
- SkillsMiddleware: Middleware to inject skills into agent's system prompt
- list_skills: List all available skills from directories
"""

from claude_code_deepagents.skills.load import (
    SkillLoader,
    SkillMetadata,
    list_skills,
)
from claude_code_deepagents.skills.middleware import SkillsMiddleware

__all__ = [
    "SkillLoader",
    "SkillMetadata",
    "SkillsMiddleware",
    "list_skills",
]

