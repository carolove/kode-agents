"""Plan sub-agent definition for deepagent.

This sub-agent specializes in analyzing the codebase and designing implementation strategies.
It is read-only and focuses on planning, not execution.

Tool Permissions: READ_ONLY_TOOLS = ["ls", "read_file", "glob", "grep", "execute"]
"""

from typing import Any
from pathlib import Path


# Default plan agent instructions
DEFAULT_PLAN_INSTRUCTIONS = """You are a planning sub-agent operating at {workspace_dir}.

Your role is to analyze the codebase and design implementation strategies WITHOUT making changes.

## Capabilities:
- Read files to understand code structure (read_file)
- List directories (ls)
- Find files using glob patterns (glob)
- Search for patterns in files (grep)
- Execute read-only shell commands (execute) - but avoid destructive commands

## Your Task:
1. Analyze the current codebase structure relevant to the task
2. Identify files that need to be created or modified
3. Design a step-by-step implementation plan
4. Identify potential challenges or considerations
5. Output a clear, numbered implementation plan

## Constraints:
- You CANNOT modify, create, or delete any files (no write_file, edit_file)
- You MUST output a structured implementation plan
- Focus on analysis and planning, not implementation

## Output Format:
Provide a numbered implementation plan like:
1. Step one description
   - Sub-details
2. Step two description
   - Sub-details
...

Include relevant file paths and specific changes needed."""


def get_plan_subagent_config(
    workspace_dir: Path | str | None = None,
    max_iterations: int = 5,  # noqa: ARG001 - kept for API consistency
    additional_tools: list[Any] | None = None,
    backend: Any = None,  # noqa: ARG001 - kept for API consistency
) -> dict[str, Any]:
    """Get configuration for the plan sub-agent.

    This subagent has READ-ONLY tools: ls, read_file, glob, grep, execute.
    It cannot modify files (no write_file, edit_file).

    Args:
        workspace_dir: Working directory for the agent
        max_iterations: Maximum execution iterations (unused, for API consistency)
        additional_tools: Additional tools to include
        backend: Backend for filesystem operations (unused, for API consistency)

    Returns:
        Sub-agent configuration dictionary for deepagent
    """
    if workspace_dir is None:
        workspace_dir = Path.cwd()
    elif isinstance(workspace_dir, str):
        workspace_dir = Path(workspace_dir)

    instructions = DEFAULT_PLAN_INSTRUCTIONS.format(
        workspace_dir=workspace_dir,
    )

    # Read-only tools for plan agent
    tools: list[Any] = []
    if additional_tools:
        tools.extend(additional_tools)

    config: dict[str, Any] = {
        "name": "plan",
        "description": (
            "Planning agent for designing implementation strategies. "
            "Use for analyzing the codebase and creating detailed implementation plans. "
            "This agent will search files, understand structure, and output a "
            "numbered plan of what changes need to be made. Focuses on analysis, not changes."
        ),
        "system_prompt": instructions,
    }

    if tools:
        config["tools"] = tools

    return config


def create_plan_subagent(
    workspace_dir: Path | str | None = None,
    max_iterations: int = 5,
    additional_tools: list[Any] | None = None,
    backend: Any = None,
) -> dict[str, Any]:
    """Create a plan sub-agent for deepagent.

    Convenience wrapper around get_plan_subagent_config.

    Args:
        workspace_dir: Working directory for the agent
        max_iterations: Maximum execution iterations
        additional_tools: Additional tools to include
        backend: Backend for filesystem operations

    Returns:
        Sub-agent configuration dictionary
    """
    return get_plan_subagent_config(
        workspace_dir=workspace_dir,
        max_iterations=max_iterations,
        additional_tools=additional_tools,
        backend=backend,
    )

