"""Claude Code Agent based on deepagents framework."""

from .config import AgentConfig, load_config
from .agent import CodingAgentSession, create_coding_agent, ContextStats

__version__ = "0.1.0"

__all__ = [
    "AgentConfig",
    "CodingAgentSession",
    "ContextStats",
    "create_coding_agent",
    "load_config",
]

