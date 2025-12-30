"""Claude Code Agent based on deepagents framework."""

from .config import AgentConfig, load_config
from .agent import CodingAgentSession, create_coding_agent, ContextStats
from .skills import SkillLoader, SkillsMiddleware, list_skills

__version__ = "0.1.0"

__all__ = [
    "AgentConfig",
    "CodingAgentSession",
    "ContextStats",
    "SkillLoader",
    "SkillsMiddleware",
    "create_coding_agent",
    "list_skills",
    "load_config",
]

