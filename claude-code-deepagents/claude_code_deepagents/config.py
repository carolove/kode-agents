"""Configuration management for claude-code-deepagents."""

import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional


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

    # Subagent Configuration
    enable_subagents: bool = True
    subagent_types: Optional[List[str]] = None  # None means all available

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
        subagent_section = ""
        if self.enable_subagents:
            subagent_section = """

Subagent Delegation:
You can spawn subagents for complex subtasks using the `task` tool:
- explore: Read-only agent for exploring code, finding files, searching. Use for reconnaissance.
- code: Full coding agent for implementing features and fixing bugs. Use for multi-step coding tasks.
- plan: Planning agent for designing implementation strategies. Returns a numbered plan.

Use subagents to:
- Isolate complex tasks and keep your context clean
- Parallelize independent work across multiple subagents
- Delegate focused tasks that require deep exploration or implementation"""

        return f"""You are a coding agent operating INSIDE the user's repository at {self.workspace_dir}.
Follow this loop strictly: plan briefly → use TOOLS to act directly on files/shell → report concise results.

Rules:
- Prefer taking actions with tools (read/write/edit/bash) over long prose.
- Keep outputs terse. Use bullet lists / checklists when summarizing.
- Never invent file paths. Ask via reads or list directories first if unsure.
- For edits, apply the smallest change that satisfies the request.
- For bash, avoid destructive or privileged commands; stay inside the workspace.
- Use the write_todos tool to maintain multi-step plans when needed.
- After finishing, summarize what changed and how to run or test.

Todo Management:
- For complex tasks with multiple steps, use write_todos to create and track a todo list.
- Each todo item should have: id, content, status (pending/in_progress/completed).
- Only ONE task can be in_progress at a time - focus on completing it before moving to the next.
- Update todo status as you progress: mark completed tasks and move to next pending task.
- Use read_todos to check current progress when resuming work.{subagent_section}"""

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

