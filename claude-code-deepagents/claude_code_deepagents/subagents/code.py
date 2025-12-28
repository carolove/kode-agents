"""Code sub-agent definition for deepagent.

This sub-agent is a full-featured coding agent for implementing features and fixing bugs.
It has access to all file operations and shell commands.
This is useful for delegating complex coding tasks that require focused context.

Tool Permissions: ALL_TOOLS = ["ls", "read_file", "write_file", "edit_file", "glob", "grep", "execute"]
"""

from typing import Any
from pathlib import Path


# Default code agent instructions
DEFAULT_CODE_INSTRUCTIONS = """You are a coding sub-agent operating at {workspace_dir}.

Your role is to implement features, fix bugs, and make code changes efficiently.

## Capabilities:
- Read files (read_file)
- Write new files (write_file)
- Edit existing files (edit_file)
- List directories (ls)
- Find files using glob patterns (glob)
- Search for patterns in files (grep)
- Execute shell commands (execute) for building, testing, and running code

## Guidelines:
- Implement the requested changes efficiently and correctly
- Apply the smallest change that satisfies the request
- Follow existing code style and patterns in the codebase
- Test your changes when appropriate
- Avoid destructive or privileged shell commands

## Output:
- Return a clear summary of what was changed
- Include file paths that were modified
- Note any tests run and their results
- Highlight any issues or concerns encountered

Be thorough in implementation but return promptly with results."""


def get_code_subagent_config(
    workspace_dir: Path | str | None = None,
    max_iterations: int = 10,  # noqa: ARG001 - kept for API consistency
    additional_tools: list[Any] | None = None,
    backend: Any = None,  # noqa: ARG001 - kept for API consistency
) -> dict[str, Any]:
    """Get configuration for the code sub-agent.

    This subagent has FULL tools access: ls, read_file, write_file, edit_file,
    glob, grep, execute.

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

    instructions = DEFAULT_CODE_INSTRUCTIONS.format(
        workspace_dir=workspace_dir,
    )

    # Code agent has full access to all tools
    tools: list[Any] = []
    if additional_tools:
        tools.extend(additional_tools)

    config: dict[str, Any] = {
        "name": "code",
        "description": (
            "Full coding agent for implementing features and fixing bugs. "
            "Use for multi-step coding tasks: creating new files, modifying "
            "existing code, running tests, and making complex changes. "
            "This agent has FULL read/write access to the workspace."
        ),
        "system_prompt": instructions,
    }

    if tools:
        config["tools"] = tools

    return config


def create_code_subagent(
    workspace_dir: Path | str | None = None,
    max_iterations: int = 10,
    additional_tools: list[Any] | None = None,
    backend: Any = None,
) -> dict[str, Any]:
    """Create a code sub-agent for deepagent.

    Convenience wrapper around get_code_subagent_config.

    Args:
        workspace_dir: Working directory for the agent
        max_iterations: Maximum execution iterations
        additional_tools: Additional tools to include
        backend: Backend for filesystem operations

    Returns:
        Sub-agent configuration dictionary
    """
    return get_code_subagent_config(
        workspace_dir=workspace_dir,
        max_iterations=max_iterations,
        additional_tools=additional_tools,
        backend=backend,
    )

