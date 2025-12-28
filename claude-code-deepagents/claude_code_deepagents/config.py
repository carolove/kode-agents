"""Configuration management for claude-code-deepagents."""

import os
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class AgentConfig:
    """Configuration for the coding agent."""

    # API Configuration
    api_key: str = field(default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY", ""))
    base_url: str = field(default_factory=lambda: os.environ.get("ANTHROPIC_BASE_URL", "https://api.moonshot.cn/anthropic"))
    model_name: str = field(default_factory=lambda: os.environ.get("AGENT_MODEL", "kimi-k2-turbo-preview"))

    # Workspace Configuration
    workspace_dir: Path = field(default_factory=Path.cwd)

    # Agent Configuration
    max_tokens: int = 16000
    max_tool_result_chars: int = 100_000

    # System Prompt
    system_prompt: str = ""

    def __post_init__(self):
        """Post initialization validation and setup."""
        if isinstance(self.workspace_dir, str):
            self.workspace_dir = Path(self.workspace_dir)

        if not self.system_prompt:
            self.system_prompt = self._default_system_prompt()

    def _default_system_prompt(self) -> str:
        """Generate the default system prompt."""
        return f"""You are a coding agent operating INSIDE the user's repository at {self.workspace_dir}.
Follow this loop strictly: plan briefly → use TOOLS to act directly on files/shell → report concise results.

Rules:
- Prefer taking actions with tools (read/write/edit/bash) over long prose.
- Keep outputs terse. Use bullet lists / checklists when summarizing.
- Never invent file paths. Ask via reads or list directories first if unsure.
- For edits, apply the smallest change that satisfies the request.
- For bash, avoid destructive or privileged commands; stay inside the workspace.
- After finishing, summarize what changed and how to run or test."""

    def validate(self) -> bool:
        """Validate the configuration."""
        if not self.api_key:
            raise ValueError("API key is required. Set ANTHROPIC_API_KEY environment variable.")
        return True


def load_config(**kwargs) -> AgentConfig:
    """Load configuration with optional overrides.

    Args:
        **kwargs: Override any config values

    Returns:
        AgentConfig instance
    """
    config = AgentConfig(**kwargs)
    config.validate()
    return config

