#!/usr/bin/env python3
"""Main entry point for claude-code-deepagents."""

import sys
import asyncio
from pathlib import Path
from typing import List, Dict, Any, Optional

# Add package root to path for direct script execution
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from claude_code_deepagents.config import load_config, AgentConfig
from claude_code_deepagents.agent import CodingAgentSession, ContextStats
from claude_code_deepagents.skills.load import list_skills

# ANSI color codes for todo rendering
RESET = "\x1b[0m"
TODO_COMPLETED_COLOR = "\x1b[38;5;243m"  # Gray for completed
TODO_PROGRESS_COLOR = "\x1b[38;5;75m"    # Blue for in_progress
TODO_PENDING_COLOR = "\x1b[38;5;250m"    # Light gray for pending
STRIKETHROUGH = "\x1b[9m"

# Colors for context stats
CONTEXT_COLOR = "\x1b[38;5;245m"         # Dim gray for context info
SUBAGENT_COLOR = "\x1b[38;5;208m"        # Orange for subagent events
DELTA_POSITIVE = "\x1b[38;5;196m"        # Red for context growth
DELTA_NEGATIVE = "\x1b[38;5;40m"         # Green for context reduction


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


def print_tool_call(name: str, args: Any) -> None:
    """Print tool call notification.

    Args:
        name: Tool name
        args: Tool arguments (can be dict or str during streaming)
    """
    # Handle args that might be a string (streaming JSON fragment) instead of dict
    if isinstance(args, str):
        # Try to parse JSON string
        import json
        try:
            args = json.loads(args)
        except (json.JSONDecodeError, ValueError):
            # If parsing fails, just display as string
            args_str = args
            if len(args_str) > 100:
                args_str = args_str[:100] + "..."
            print(f"\n  🔧 {name}({args_str})")
            return

    # Special handling for subagent task calls
    if name == "task" and isinstance(args, dict):
        subagent_type = args.get("subagent_type", "unknown")
        description = args.get("description", "")
        # Truncate description for display
        if len(description) > 80:
            description = description[:80] + "..."
        print(f"\n  🚀 [SUBAGENT:{subagent_type}] {description}")
        return

    # Regular tool call display
    args_str = str(args)
    if len(args_str) > 100:
        args_str = args_str[:100] + "..."
    print(f"\n  🔧 {name}({args_str})")


def print_context_stats(before: ContextStats, after: ContextStats, event_type: Optional[str]) -> None:
    """Print context statistics with delta information.

    Args:
        before: Stats before the event
        after: Stats after the event
        event_type: Type of event (start, subagent_call, subagent_activity, update, end)
    """
    if event_type == "start":
        print(f"\n  {CONTEXT_COLOR}📊 [Context Start] msgs={before.message_count} chars={before.total_chars:,}{RESET}")
        return

    if event_type == "subagent_call":
        print(f"\n  {SUBAGENT_COLOR}📤 [Subagent Call #{after.subagent_calls}] "
              f"Main context remains: msgs={before.message_count} chars={before.total_chars:,}{RESET}")
        return

    if event_type == "subagent_activity":
        # Subagent is working in isolated context - show this info
        print(f"\n  {SUBAGENT_COLOR}⚡ [Subagent Working] "
              f"Subagent context: msgs={after.message_count} chars={after.total_chars:,} "
              f"(isolated from main){RESET}")
        return

    if event_type == "end":
        delta_msgs = after.message_count - before.message_count
        delta_chars = after.total_chars - before.total_chars

        # Color based on whether context grew or shrank
        if delta_chars > 0:
            delta_color = DELTA_POSITIVE
            delta_sign = "+"
        elif delta_chars < 0:
            delta_color = DELTA_NEGATIVE
            delta_sign = ""
        else:
            delta_color = CONTEXT_COLOR
            delta_sign = ""

        print(f"\n  {CONTEXT_COLOR}📊 [Context End] msgs={after.message_count} chars={after.total_chars:,} "
              f"{delta_color}(Δ {delta_sign}{delta_msgs} msgs, {delta_sign}{delta_chars:,} chars){RESET}")

        # If subagents were used, show the efficiency
        if after.subagent_calls > 0:
            print(f"  {SUBAGENT_COLOR}   └─ Subagent calls: {after.subagent_calls}, "
                  f"Result chars added to main: {after.subagent_result_chars:,}{RESET}")
        return


def print_skills(skills: List[Dict[str, Any]]) -> None:
    """Print available skills in a formatted list.

    Args:
        skills: List of SkillMetadata dictionaries
    """
    if not skills:
        print(f"{CONTEXT_COLOR}No skills available. Create skills in ~/.deepagents/claude-code/skills/ or ./.deepagents/skills/{RESET}")
        return

    print(f"\n{SUBAGENT_COLOR}📚 Available Skills:{RESET}")

    for skill in skills:
        source = skill.get("source", "unknown")
        name = skill.get("name", "unnamed")
        description = skill.get("description", "No description")
        path = skill.get("path", "")

        # Color based on source
        if source == "project":
            color = "\x1b[38;5;46m"  # Green for project skills
            source_marker = "[project]"
        else:  # user
            color = "\x1b[38;5;75m"   # Blue for user skills
            source_marker = "[user]"

        # Display skill info
        print(f"  {color}• {name} {source_marker}{RESET}")
        print(f"    {description}")
        if path:
            # Show relative path if possible
            try:
                rel_path = Path(path).relative_to(Path.cwd())
                path_str = f"./{rel_path}"
            except ValueError:
                path_str = path
            print(f"    {CONTEXT_COLOR}📄 {path_str}{RESET}")
        print()


async def run_interactive_async(config: AgentConfig, show_context_stats: bool = True):
    """Run the interactive REPL session with async streaming.

    Args:
        config: Agent configuration
        show_context_stats: Whether to show context statistics (default: True)
    """
    print(f"Claude Code Agent (deepagents) — cwd: {config.workspace_dir}")
    if show_context_stats:
        print("Context tracking enabled. Use 'stats' to see current context size.")
    print('Type "exit" or "quit" to leave.')
    print('Use "skills list" to see available skills.\n')

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

        # Special command to show current stats
        if line.strip().lower() == "stats":
            stats = session.get_context_stats()
            print(f"\n{CONTEXT_COLOR}{stats}{RESET}\n")
            continue

        # Special command to show available skills
        if line.strip().lower() == "skills list":
            skills = list_skills(
                user_skills_dir=config.user_skills_dir,
                project_skills_dir=config.project_skills_dir
            )
            print_skills(skills)
            continue

        print("\n● ", end="")
        sys.stdout.flush()

        try:
            # Only pass context stats callback if enabled
            context_callback = print_context_stats if show_context_stats else None

            response = await session.astream_with_events(
                line,
                on_todos=print_todos,
                on_text=print_text,
                on_tool_call=print_tool_call,
                on_context_stats=context_callback,
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

