"""Explore sub-agent definition for deepagent.

This sub-agent is a read-only agent for exploring code, finding files, and searching.
It has access to file reading and shell commands but cannot modify files.
This is useful for context isolation when exploring the codebase without
polluting the main agent's context.

Tool Permissions: READ_ONLY_TOOLS = ["ls", "read_file", "glob", "grep", "execute"]
"""

from typing import Any
from pathlib import Path


# Default explore agent instructions
DEFAULT_EXPLORE_INSTRUCTIONS = """You are an exploration sub-agent operating at {workspace_dir}.

Your role is to search, analyze, and explore the codebase WITHOUT making any modifications.

## Capabilities:
- Read files to understand code structure and content (read_file)
- List directories (ls)
- Find files using glob patterns (glob)
- Search for patterns in files (grep)
- Execute read-only shell commands (execute) - but avoid destructive commands

## Constraints:
- You CANNOT modify, create, or delete any files (no write_file, edit_file)
- You CANNOT run destructive shell commands
- Focus on gathering information and providing concise summaries

## Output:
- Return a clear, concise summary of your findings
- Include relevant file paths, code snippets, or patterns found
- Highlight key insights that will help the main agent

Be thorough but efficient. Complete your exploration and return findings promptly."""


def get_explore_subagent_config(
    workspace_dir: Path | str | None = None,
    max_iterations: int = 5,  # noqa: ARG001 - kept for API consistency
    additional_tools: list[Any] | None = None,
    backend: Any = None,  # noqa: ARG001 - kept for API consistency
) -> dict[str, Any]:
    """Get configuration for the explore sub-agent.

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

    instructions = DEFAULT_EXPLORE_INSTRUCTIONS.format(
        workspace_dir=workspace_dir,
    )

    # Read-only tools for explore agent
    # Note: We explicitly define the tools to prevent FilesystemMiddleware
    # from adding write_file and edit_file
    tools: list[Any] = []
    if additional_tools:
        tools.extend(additional_tools)

    config: dict[str, Any] = {
        "name": "explore",
        "description": (
            "Fast read-only agent for exploring codebases, finding files, and searching. "
            "Use for reconnaissance tasks: understanding codebase structure, "
            "finding relevant files, searching for patterns, or gathering "
            "information before making changes. This agent focuses on read-only operations."
        ),
        "system_prompt": instructions,
    }

    if tools:
        config["tools"] = tools

    return config


def create_explore_subagent(
    workspace_dir: Path | str | None = None,
    max_iterations: int = 5,
    additional_tools: list[Any] | None = None,
    backend: Any = None,
) -> dict[str, Any]:
    """Create an explore sub-agent for deepagent.

    Convenience wrapper around get_explore_subagent_config.

    Args:
        workspace_dir: Working directory for the agent
        max_iterations: Maximum execution iterations
        additional_tools: Additional tools to include
        backend: Backend for filesystem operations

    Returns:
        Sub-agent configuration dictionary
    """
    return get_explore_subagent_config(
        workspace_dir=workspace_dir,
        max_iterations=max_iterations,
        additional_tools=additional_tools,
        backend=backend,
    )

