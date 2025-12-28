#!/usr/bin/env python3
"""Main entry point for claude-code-deepagents."""

import sys
import asyncio
from pathlib import Path
from typing import List, Dict, Any

# Add package root to path for direct script execution
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from claude_code_deepagents.config import load_config, AgentConfig
from claude_code_deepagents.agent import CodingAgentSession

# ANSI color codes for todo rendering
RESET = "\x1b[0m"
TODO_COMPLETED_COLOR = "\x1b[38;5;243m"  # Gray for completed
TODO_PROGRESS_COLOR = "\x1b[38;5;75m"    # Blue for in_progress
TODO_PENDING_COLOR = "\x1b[38;5;250m"    # Light gray for pending
STRIKETHROUGH = "\x1b[9m"


def render_todo(todo: Dict[str, Any]) -> str:
    """Render a single todo item with colors.

    Args:
        todo: Todo dict with 'content' and 'status' keys

    Returns:
        Colored string representation
    """
    status = todo.get("status", "pending")
    content = todo.get("content", "")

    if status == "completed":
        mark = "☒"
        return f"{TODO_COMPLETED_COLOR}{STRIKETHROUGH}{mark} {content}{RESET}"
    elif status == "in_progress":
        mark = "☐"
        return f"{TODO_PROGRESS_COLOR}{mark} {content}{RESET}"
    else:  # pending
        mark = "☐"
        return f"{TODO_PENDING_COLOR}{mark} {content}{RESET}"


def render_todos(todos: List[Dict[str, Any]]) -> str:
    """Render the full todo list.

    Args:
        todos: List of todo items

    Returns:
        Formatted todo list string
    """
    if not todos:
        return ""

    lines = ["", "📋 Todo List:"]
    for todo in todos:
        lines.append("  " + render_todo(todo))
    lines.append("")
    return "\n".join(lines)


def print_todos(todos: List[Dict[str, Any]]) -> None:
    """Print the todos list to terminal."""
    if todos:
        print(render_todos(todos))


def print_text(text: str) -> None:
    """Print text chunk to terminal."""
    sys.stdout.write(text)
    sys.stdout.flush()


def print_tool_call(name: str, args: Dict[str, Any]) -> None:
    """Print tool call notification."""
    # Truncate args for display
    args_str = str(args)
    if len(args_str) > 100:
        args_str = args_str[:100] + "..."
    print(f"\n  🔧 {name}({args_str})")


async def run_interactive_async(config: AgentConfig):
    """Run the interactive REPL session with async streaming.

    Args:
        config: Agent configuration
    """
    print(f"Claude Code Agent (deepagents) — cwd: {config.workspace_dir}")
    print('Type "exit" or "quit" to leave.\n')

    session = CodingAgentSession(config)

    while True:
        try:
            line = input("User: ")
        except EOFError:
            break
        except KeyboardInterrupt:
            print("\n")
            break

        if not line or line.strip().lower() in {"q", "quit", "exit"}:
            break

        print("\n● ", end="")
        sys.stdout.flush()

        try:
            response = await session.astream_with_events(
                line,
                on_todos=print_todos,
                on_text=print_text,
                on_tool_call=print_tool_call,
            )
            print("\n")
        except Exception as e:
            print(f"\nError: {e}\n")


def run_interactive(config: AgentConfig):
    """Run the interactive REPL session.

    Args:
        config: Agent configuration
    """
    asyncio.run(run_interactive_async(config))


def main():
    """Main entry point."""
    try:
        config = load_config()
    except ValueError as e:
        print(f"❌ Configuration error: {e}", file=sys.stderr)
        sys.exit(1)

    run_interactive(config)


if __name__ == "__main__":
    main()

