#!/usr/bin/env python3
"""
v3_subagent.py - Mini Claude Code: + Subagent Mechanism (~450 lines)

Builds on v2 by adding the Task tool for spawning subagents.
This solves "context pollution": exploration details don't clutter the main conversation.

New concepts:
- AGENT_TYPES: Registry defining agent capabilities
- Task tool: Spawns isolated child agents
- Tool filtering: Each agent type has its own tool whitelist
- Recursive query: Subagents reuse the same loop

Usage:
    python v3_subagent.py
"""

import subprocess
import sys
import time
from pathlib import Path

try:
    from anthropic import Anthropic
except ImportError:
    sys.exit("pip install anthropic")

# =============================================================================
# Configuration
# =============================================================================
API_KEY = "sk-xxx"  # Replace with your API key
BASE_URL = "https://api.moonshot.cn/anthropic"
MODEL = "claude-sonnet-4-20250514"
WORKDIR = Path.cwd()

client = Anthropic(api_key=API_KEY, base_url=BASE_URL) if BASE_URL else Anthropic(api_key=API_KEY)

# =============================================================================
# Agent Type Registry - Core of the subagent mechanism
# =============================================================================
AGENT_TYPES = {
    "explore": {
        "description": "Read-only agent for exploring code, finding files, searching",
        "tools": ["bash", "read_file"],  # No write access
        "prompt": "You are an exploration agent. Search and analyze, but never modify files. Return a concise summary.",
    },
    "code": {
        "description": "Full agent for implementing features and fixing bugs",
        "tools": "*",  # All tools
        "prompt": "You are a coding agent. Implement the requested changes efficiently.",
    },
    "plan": {
        "description": "Planning agent for designing implementation strategies",
        "tools": ["bash", "read_file"],  # Read-only
        "prompt": "You are a planning agent. Analyze the codebase and output a numbered implementation plan. Do NOT make changes.",
    },
}


def get_agent_descriptions() -> str:
    """Generate descriptions for Task tool."""
    lines = []
    for name, config in AGENT_TYPES.items():
        lines.append(f"- {name}: {config['description']}")
    return "\n".join(lines)


# =============================================================================
# TodoManager (from v2)
# =============================================================================
class TodoManager:
    def __init__(self):
        self.items = []

    def update(self, items: list) -> str:
        validated = []
        in_progress = 0

        for i, item in enumerate(items):
            content = str(item.get("content", "")).strip()
            status = str(item.get("status", "pending")).lower()
            active = str(item.get("activeForm", "")).strip()

            if not content or not active:
                raise ValueError(f"Item {i}: content and activeForm required")
            if status not in ("pending", "in_progress", "completed"):
                raise ValueError(f"Item {i}: invalid status")
            if status == "in_progress":
                in_progress += 1

            validated.append({"content": content, "status": status, "activeForm": active})

        if in_progress > 1:
            raise ValueError("Only one task can be in_progress")

        self.items = validated[:20]
        return self.render()

    def render(self) -> str:
        if not self.items:
            return "No todos."
        lines = []
        for t in self.items:
            mark = "[x]" if t["status"] == "completed" else "[>]" if t["status"] == "in_progress" else "[ ]"
            lines.append(f"{mark} {t['content']}")
        done = sum(1 for t in self.items if t["status"] == "completed")
        return "\n".join(lines) + f"\n({done}/{len(self.items)} done)"


TODO = TodoManager()

# =============================================================================
# System Prompt
# =============================================================================
SYSTEM = f"""You are a coding agent at {WORKDIR}.

Loop: plan -> act with tools -> report.

You can spawn subagents for complex subtasks:
{get_agent_descriptions()}

Rules:
- Use Task tool for subtasks that need focused exploration or implementation
- Use TodoWrite to track multi-step work
- Prefer tools over prose. Act, don't just explain.
- After finishing, summarize what changed."""

# =============================================================================
# Base Tool Definitions
# =============================================================================
BASE_TOOLS = [
    {
        "name": "bash",
        "description": "Run shell command.",
        "input_schema": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
    },
    {
        "name": "read_file",
        "description": "Read file contents.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}},
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write to file.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
        },
    },
    {
        "name": "edit_file",
        "description": "Replace text in file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_text": {"type": "string"},
                "new_text": {"type": "string"},
            },
            "required": ["path", "old_text", "new_text"],
        },
    },
    {
        "name": "TodoWrite",
        "description": "Update task list.",
        "input_schema": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "content": {"type": "string"},
                            "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]},
                            "activeForm": {"type": "string"},
                        },
                        "required": ["content", "status", "activeForm"],
                    },
                }
            },
            "required": ["items"],
        },
    },
]

# Task tool - for spawning subagents
TASK_TOOL = {
    "name": "Task",
    "description": f"Spawn a subagent for a focused subtask.\n\nAgent types:\n{get_agent_descriptions()}",
    "input_schema": {
        "type": "object",
        "properties": {
            "description": {"type": "string", "description": "Short task description (3-5 words)"},
            "prompt": {"type": "string", "description": "Detailed instructions for the subagent"},
            "agent_type": {"type": "string", "enum": list(AGENT_TYPES.keys())},
        },
        "required": ["description", "prompt", "agent_type"],
    },
}

# Main agent gets all tools including Task
ALL_TOOLS = BASE_TOOLS + [TASK_TOOL]


def get_tools_for_agent(agent_type: str) -> list:
    """Filter tools based on agent type."""
    allowed = AGENT_TYPES.get(agent_type, {}).get("tools", "*")
    if allowed == "*":
        return BASE_TOOLS  # Subagents don't get Task (no nesting in demo)
    return [t for t in BASE_TOOLS if t["name"] in allowed]


# =============================================================================
# Tool Implementations
# =============================================================================
def safe_path(p: str) -> Path:
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {p}")
    return path


def run_bash(cmd: str) -> str:
    if any(d in cmd for d in ["rm -rf /", "sudo", "shutdown"]):
        return "Error: Dangerous command"
    try:
        r = subprocess.run(cmd, shell=True, cwd=WORKDIR, capture_output=True, text=True, timeout=60)
        return ((r.stdout + r.stderr).strip() or "(no output)")[:50000]
    except Exception as e:
        return f"Error: {e}"


def run_read(path: str, limit: int = None) -> str:
    try:
        lines = safe_path(path).read_text().splitlines()
        if limit:
            lines = lines[:limit]
        return "\n".join(lines)[:50000]
    except Exception as e:
        return f"Error: {e}"


def run_write(path: str, content: str) -> str:
    try:
        fp = safe_path(path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
        return f"Wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error: {e}"


def run_edit(path: str, old_text: str, new_text: str) -> str:
    try:
        fp = safe_path(path)
        text = fp.read_text()
        if old_text not in text:
            return f"Error: Text not found in {path}"
        fp.write_text(text.replace(old_text, new_text, 1))
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"


def run_todo(items: list) -> str:
    try:
        return TODO.update(items)
    except Exception as e:
        return f"Error: {e}"


# =============================================================================
# Subagent Execution - The heart of Task tool
# =============================================================================
def run_task(description: str, prompt: str, agent_type: str) -> str:
    """
    Execute a subagent task:
    1. Create isolated message history
    2. Use agent-specific system prompt
    3. Filter available tools
    4. Run the same query loop
    5. Return only final text
    """
    if agent_type not in AGENT_TYPES:
        return f"Error: Unknown agent type '{agent_type}'"

    config = AGENT_TYPES[agent_type]

    # Agent-specific system prompt
    sub_system = f"""You are a {agent_type} subagent at {WORKDIR}.

{config['prompt']}

Complete the task and return a clear, concise summary."""

    # Filtered tools for this agent type
    sub_tools = get_tools_for_agent(agent_type)

    # Isolated message history (key: no parent context)
    sub_messages = [{"role": "user", "content": prompt}]

    # Progress display
    print(f"  [{agent_type}] {description}")
    start = time.time()
    tool_count = 0

    # Run query loop (silent mode - don't print to main chat)
    while True:
        response = client.messages.create(
            model=MODEL,
            system=sub_system,
            messages=sub_messages,
            tools=sub_tools,
            max_tokens=8000,
        )

        if response.stop_reason != "tool_use":
            break

        tool_calls = [b for b in response.content if b.type == "tool_use"]
        results = []

        for tc in tool_calls:
            tool_count += 1
            output = execute_tool(tc.name, tc.input)
            results.append({"type": "tool_result", "tool_use_id": tc.id, "content": output})

            # Update progress line
            elapsed = time.time() - start
            sys.stdout.write(f"\r  [{agent_type}] {description} ... {tool_count} tools, {elapsed:.1f}s")
            sys.stdout.flush()

        sub_messages.append({"role": "assistant", "content": response.content})
        sub_messages.append({"role": "user", "content": results})

    # Clear progress line and print summary
    elapsed = time.time() - start
    sys.stdout.write(f"\r  [{agent_type}] {description} - done ({tool_count} tools, {elapsed:.1f}s)\n")

    # Extract final text
    for block in response.content:
        if hasattr(block, "text"):
            return block.text

    return "(subagent returned no text)"


def execute_tool(name: str, input: dict) -> str:
    """Dispatch tool call."""
    if name == "bash":
        return run_bash(input["command"])
    elif name == "read_file":
        return run_read(input["path"], input.get("limit"))
    elif name == "write_file":
        return run_write(input["path"], input["content"])
    elif name == "edit_file":
        return run_edit(input["path"], input["old_text"], input["new_text"])
    elif name == "TodoWrite":
        return run_todo(input["items"])
    elif name == "Task":
        return run_task(input["description"], input["prompt"], input["agent_type"])
    return f"Unknown tool: {name}"


# =============================================================================
# Main Agent Loop
# =============================================================================
def agent_loop(messages: list) -> list:
    while True:
        response = client.messages.create(
            model=MODEL,
            system=SYSTEM,
            messages=messages,
            tools=ALL_TOOLS,
            max_tokens=8000,
        )

        tool_calls = []
        for block in response.content:
            if hasattr(block, "text"):
                print(block.text)
            if block.type == "tool_use":
                tool_calls.append(block)

        if response.stop_reason != "tool_use":
            messages.append({"role": "assistant", "content": response.content})
            return messages

        results = []
        for tc in tool_calls:
            # Task tool has special display handling
            if tc.name == "Task":
                print(f"\n> Task: {tc.input.get('description', 'subtask')}")
            else:
                print(f"\n> {tc.name}")

            output = execute_tool(tc.name, tc.input)

            # Don't print full Task output (it manages its own display)
            if tc.name != "Task":
                print(f"  {output[:200]}{'...' if len(output) > 200 else ''}")

            results.append({"type": "tool_result", "tool_use_id": tc.id, "content": output})

        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": results})


# =============================================================================
# Main REPL
# =============================================================================
def main():
    print(f"Mini Claude Code v3 (with Subagents) - {WORKDIR}")
    print(f"Agent types: {', '.join(AGENT_TYPES.keys())}")
    print("Type 'exit' to quit.\n")

    history = []

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not user_input or user_input.lower() in ("exit", "quit", "q"):
            break

        history.append({"role": "user", "content": user_input})

        try:
            agent_loop(history)
        except Exception as e:
            print(f"Error: {e}")

        print()


if __name__ == "__main__":
    main()