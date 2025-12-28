"""Sub-agent definitions for deepagent delegation.

This module provides subagent configurations for the claude-code-deepagents project.
Subagents allow for context isolation and focused task execution.

Available Subagents:
- explore: For exploring and analyzing codebases (read-only focus in system prompt)
- code: For implementing features and fixing bugs (full access)
- plan: For creating implementation plans (read-only focus in system prompt)
"""

from typing import Any, Callable

from .explore import create_explore_subagent, get_explore_subagent_config
from .code import create_code_subagent, get_code_subagent_config
from .plan import create_plan_subagent, get_plan_subagent_config

# Registry mapping subagent names to their creation functions
SUBAGENT_REGISTRY: dict[str, Callable[..., dict[str, Any]]] = {
    "explore": create_explore_subagent,
    "code": create_code_subagent,
    "plan": create_plan_subagent,
}


def create_subagent_by_name(
    name: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """Create a subagent by name using the registry.

    Args:
        name: Name of the subagent (e.g., "explore", "code", "plan")
        **kwargs: Additional arguments passed to the subagent creation function

    Returns:
        Configured subagent dictionary

    Raises:
        ValueError: If subagent name is not found in registry
    """
    if name not in SUBAGENT_REGISTRY:
        available = ", ".join(SUBAGENT_REGISTRY.keys())
        msg = f"Unknown subagent: '{name}'. Available: {available}"
        raise ValueError(msg)

    create_fn = SUBAGENT_REGISTRY[name]
    return create_fn(**kwargs)


def create_subagents_from_names(
    names: list[str] | None = None,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    """Create multiple subagents from a list of names.

    Args:
        names: List of subagent names to create. If None, creates all available.
        **kwargs: Additional arguments passed to all subagent creation functions

    Returns:
        List of configured subagent dictionaries
    """
    if names is None:
        names = list(SUBAGENT_REGISTRY.keys())

    subagents = []
    for name in names:
        spec = create_subagent_by_name(name, **kwargs)
        subagents.append(spec)

    return subagents


__all__ = [
    "SUBAGENT_REGISTRY",
    "create_code_subagent",
    "create_explore_subagent",
    "create_plan_subagent",
    "create_subagent_by_name",
    "create_subagents_from_names",
    "get_code_subagent_config",
    "get_explore_subagent_config",
    "get_plan_subagent_config",
]

