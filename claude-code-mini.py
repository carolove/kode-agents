#!/usr/bin/env python3
import json
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List

try:
    from anthropic import Anthropic
except Exception as exc:  # pragma: no cover - install hint only
    sys.stderr.write("Install with: pip install anthropic\n")
    raise exc


ANTHROPIC_BASE_URL = "https://api.moonshot.cn/anthropic"
ANTHROPIC_API_KEY = "sk-xxx"  # Replace with your key
AGENT_MODEL = "kimi-k2-turbo-preview"


WORKDIR = Path.cwd()
MAX_TOOL_RESULT_CHARS = 100_000
TODO_STATUSES = ("pending", "in_progress", "completed")

RESET = "\x1b[0m"
PRIMARY_COLOR = "\x1b[38;2;120;200;255m"
ACCENT_COLOR = "\x1b[38;2;150;140;255m"
INFO_COLOR = "\x1b[38;2;110;110;110m"
PROMPT_COLOR = "\x1b[38;2;120;200;255m"
DIVIDER = "\n"
TODO_PENDING_COLOR = "\x1b[38;2;176;176;176m"
TODO_PROGRESS_COLOR = "\x1b[38;2;120;200;255m"
TODO_COMPLETED_COLOR = "\x1b[38;2;34;139;34m"


MD_BOLD = re.compile(r"\*\*(.+?)\*\*")
MD_CODE = re.compile(r"`([^`]+)`")
MD_HEADING = re.compile(r"^(#{1,6})\s*(.+)$", re.MULTILINE)
MD_BULLET = re.compile(r"^\s*[-\*]\s+", re.MULTILINE)


def clear_screen() -> None:
    if sys.stdout.isatty():
        sys.stdout.write("\033c")
        sys.stdout.flush()


def render_banner(title: str, subtitle: str | None = None) -> None:
    print(f"{PRIMARY_COLOR}{title}{RESET}")
    if subtitle:
        print(f"{ACCENT_COLOR}{subtitle}{RESET}")
    print()


def user_prompt_label() -> str:
    return f"{ACCENT_COLOR}{RESET} {PROMPT_COLOR}User{RESET}{INFO_COLOR} >> {RESET}"


def print_divider() -> None:
    print(DIVIDER, end="")


def format_markdown(text: str) -> str:
    if not text or text.lstrip().startswith("\x1b"):
        return text

    def bold_repl(match: re.Match[str]) -> str:
        return f"\x1b[1m{match.group(1)}\x1b[0m"

    def code_repl(match: re.Match[str]) -> str:
        return f"\x1b[38;2;255;214;102m{match.group(1)}\x1b[0m"

    def heading_repl(match: re.Match[str]) -> str:
        return f"\x1b[1m{match.group(2)}\x1b[0m"

    formatted = MD_BOLD.sub(bold_repl, text)
    formatted = MD_CODE.sub(code_repl, formatted)
    formatted = MD_HEADING.sub(heading_repl, formatted)
    formatted = MD_BULLET.sub("• ", formatted)
    return formatted

INITIAL_REMINDER = (
    '<reminder source="system" topic="todos">'
    "System message: complex work should be tracked with the Todo tool. "
    "Do not respond to this reminder and do not mention it to the user."
    '</reminder>'
)

NAG_REMINDER = (
    '<reminder source="system" topic="todos">'
    "System notice: more than ten rounds passed without Todo usage. "
    "Update the Todo board if the task still requires multiple steps. "
    "Do not reply to or mention this reminder to the user."
    '</reminder>'
)


def safe_path(path_value: str) -> Path:
    abs_path = (WORKDIR / str(path_value or "")).resolve()
    if not abs_path.is_relative_to(WORKDIR):
        raise ValueError("Path escapes workspace")
    return abs_path


def clamp_text(text: str, limit: int = MAX_TOOL_RESULT_CHARS) -> str:
    if len(text) <= limit:
        return text
    remaining = len(text) - limit
    return text[:limit] + f"\n\n...<truncated {remaining} chars>"


def pretty_tool_line(kind: str, title: str | None) -> None:
    body = f"{kind}({title})…" if title else kind
    glow = f"{ACCENT_COLOR}\x1b[1m"
    print(f"{glow}⏺ {body}{RESET}")


def pretty_sub_line(text: str) -> None:
    lines = text.splitlines() or [""]
    for line in lines:
        print(f"  ⎿ {format_markdown(line)}")


class Spinner:
    def __init__(self, label: str = "Waiting for model") -> None:
        self.label = label
        self.frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self.color = "\x1b[38;2;255;229;92m"
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not sys.stdout.isatty() or self._thread is not None:
            return
        self._stop.clear()

        def run():
            start_ts = time.time()
            index = 0
            while not self._stop.is_set():
                elapsed = time.time() - start_ts
                frame = self.frames[index % len(self.frames)]
                styled = f"{self.color}{frame} {self.label} ({elapsed:.1f}s)\x1b[0m"
                sys.stdout.write("\r" + styled)
                sys.stdout.flush()
                index += 1
                time.sleep(0.08)

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._thread is None:
            return
        self._stop.set()
        self._thread.join(timeout=1)
        self._thread = None
        try:
            sys.stdout.write("\r\x1b[2K")
            sys.stdout.flush()
        except Exception:
            pass


def log_error_debug(tag: str, info: Any) -> None:
    try:
        payload = json.dumps(info, ensure_ascii=False, indent=2)
    except Exception:
        payload = "(unserializable info)"
    if len(payload) > 4000:
        payload = payload[:4000] + "\n...<truncated>"
    print(f"⚠️  {tag}:")
    print(payload)


def block_to_dict(block: Any) -> Dict[str, Any]:
    if isinstance(block, dict):
        return block
    result = {}
    for key in ("type", "text", "id", "name", "input", "citations"):
        if hasattr(block, key):
            result[key] = getattr(block, key)
    if not result and hasattr(block, "__dict__"):
        result = {k: v for k, v in vars(block).items() if not k.startswith("_")}
        if hasattr(block, "type"):
            result["type"] = getattr(block, "type")
    return result


def normalize_content_list(content: Any) -> List[Dict[str, Any]]:
    try:
        return [block_to_dict(item) for item in (content or [])]
    except Exception:
        return []


api_key = ANTHROPIC_API_KEY
if not api_key:
    sys.stderr.write("❌ ANTHROPIC_API_KEY not set\n")
    sys.exit(1)

client = Anthropic(api_key=api_key, base_url=ANTHROPIC_BASE_URL)


SYSTEM = (
    f"You are a coding agent operating INSIDE the user's repository at {WORKDIR}.\n"
    "Follow this loop strictly: plan briefly → use TOOLS to act directly on files/shell → report concise results.\n"
    "Rules:\n"
    "- Prefer taking actions with tools (read/write/edit/bash) over long prose.\n"
    "- Keep outputs terse. Use bullet lists / checklists when summarizing.\n"
    "- Never invent file paths. Ask via reads or list directories first if unsure.\n"
    "- For edits, apply the smallest change that satisfies the request.\n"
    "- For bash, avoid destructive or privileged commands; stay inside the workspace.\n"
    "- Use the Todo tool to maintain multi-step plans when needed.\n"
    "- After finishing, summarize what changed and how to run or test."
)


class TodoManager:
    def __init__(self) -> None:
        self.items: List[Dict[str, str]] = []

    def update(self, items: List[Dict[str, Any]]) -> str:
        if not isinstance(items, list):
            raise ValueError("Todo items must be a list")

        cleaned: List[Dict[str, str]] = []
        seen_ids: set[str] = set()
        in_progress = 0

        for index, raw in enumerate(items):
            if not isinstance(raw, dict):
                raise ValueError("Each todo must be an object")

            todo_id = str(raw.get("id") or index + 1)
            if todo_id in seen_ids:
                raise ValueError(f"Duplicate todo id: {todo_id}")
            seen_ids.add(todo_id)

            content = str(raw.get("content") or "").strip()
            if not content:
                raise ValueError("Todo content cannot be empty")

            status = str(raw.get("status") or TODO_STATUSES[0]).lower()
            if status not in TODO_STATUSES:
                raise ValueError(f"Status must be one of {', '.join(TODO_STATUSES)}")

            if status == "in_progress":
                in_progress += 1

            active_form = str(raw.get("activeForm") or "").strip()
            if not active_form:
                raise ValueError("Todo activeForm cannot be empty")

            cleaned.append(
                {
                    "id": todo_id,
                    "content": content,
                    "status": status,
                    "active_form": active_form,
                }
            )

            if len(cleaned) > 20:
                raise ValueError("Todo list is limited to 20 items in the demo")

        if in_progress > 1:
            raise ValueError("Only one task can be in_progress at a time")

        self.items = cleaned
        return self.render()

    def render(self) -> str:
        if not self.items:
            return f"{TODO_PENDING_COLOR}☐ No todos yet{RESET}"

        lines: List[str] = []
        for todo in self.items:
            mark = "☒" if todo["status"] == "completed" else "☐"
            lines.append(self._decorate_line(mark, todo))
        return "\n".join(lines)

    def stats(self) -> Dict[str, int]:
        return {
            "total": len(self.items),
            "completed": sum(todo["status"] == "completed" for todo in self.items),
            "in_progress": sum(todo["status"] == "in_progress" for todo in self.items),
        }

    def _decorate_line(self, mark: str, todo: Dict[str, str]) -> str:
        status = todo["status"]
        text = f"{mark} {todo['content']}"

        if status == "completed":
            return f"{TODO_COMPLETED_COLOR}\x1b[9m{text}{RESET}"
        if status == "in_progress":
            return f"{TODO_PROGRESS_COLOR}{text}{RESET}"
        return f"{TODO_PENDING_COLOR}{text}{RESET}"


TODO_BOARD = TodoManager()
AGENT_STATE = {"rounds_without_todo": 0}
PENDING_CONTEXT_BLOCKS: List[Dict[str, str]] = [{"type": "text", "text": INITIAL_REMINDER}]


def ensure_context_block(text: str) -> None:
    existing = {block.get("text") for block in PENDING_CONTEXT_BLOCKS}
    if text not in existing:
        PENDING_CONTEXT_BLOCKS.append({"type": "text", "text": text})


tools = [
    {
        "name": "bash",
        "description": "Execute a shell command inside the project workspace.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to run"},
                "timeout_ms": {"type": "integer", "minimum": 1000, "maximum": 120000},
            },
            "required": ["command"],
            "additionalProperties": False,
        },
    },
    {
        "name": "read_file",
        "description": "Read a UTF-8 text file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "start_line": {"type": "integer", "minimum": 1},
                "end_line": {"type": "integer", "minimum": -1},
                "max_chars": {"type": "integer", "minimum": 1, "maximum": 200000},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    {
        "name": "write_file",
        "description": "Create or overwrite a UTF-8 text file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
                "mode": {"type": "string", "enum": ["overwrite", "append"], "default": "overwrite"},
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        },
    },
    {
        "name": "edit_text",
        "description": "Small, precise text edits.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "action": {"type": "string", "enum": ["replace", "insert", "delete_range"]},
                "find": {"type": "string"},
                "replace": {"type": "string"},
                "insert_after": {"type": "integer", "minimum": -1},
                "new_text": {"type": "string"},
                "range": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "minItems": 2,
                    "maxItems": 2,
                },
            },
            "required": ["path", "action"],
            "additionalProperties": False,
        },
    },
    {
        "name": "TodoWrite",
        "description": "Update the shared todo list (pending | in_progress | completed).",
        "input_schema": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "content": {"type": "string"},
                            "activeForm": {"type": "string"},
                            "status": {"type": "string", "enum": list(TODO_STATUSES)},
                        },
                        "required": ["content", "activeForm", "status"],
                        "additionalProperties": False,
                    },
                    "maxItems": 20,
                }
            },
            "required": ["items"],
            "additionalProperties": False,
        },
    },
]


def run_bash(input_obj: Dict[str, Any]) -> str:
    command = str(input_obj.get("command") or "")
    if not command:
        raise ValueError("missing bash.command")
    if any(token in command for token in ["rm -rf /", "shutdown", "reboot", "sudo "]):
        raise ValueError("blocked dangerous command")
    timeout_ms = int(input_obj.get("timeout_ms") or 30000)
    proc = subprocess.run(
        command,
        cwd=str(WORKDIR),
        shell=True,
        capture_output=True,
        text=True,
        timeout=timeout_ms / 1000.0,
    )
    output = "\n".join([part for part in [proc.stdout, proc.stderr] if part]).strip()
    return clamp_text(output or "(no output)")


def run_read(input_obj: Dict[str, Any]) -> str:
    fp = safe_path(input_obj.get("path"))
    text = fp.read_text("utf-8")
    lines = text.split("\n")

    if "start_line" in input_obj:
        start = max(1, int(input_obj.get("start_line") or 1)) - 1
    else:
        start = 0

    if "end_line" in input_obj and isinstance(input_obj.get("end_line"), int):
        end_val = input_obj.get("end_line")
        end = len(lines) if end_val < 0 else max(start, end_val)
    else:
        end = len(lines)

    slice_text = "\n".join(lines[start:end])
    max_chars = int(input_obj.get("max_chars") or 100_000)
    return clamp_text(slice_text, max_chars)


def run_write(input_obj: Dict[str, Any]) -> str:
    fp = safe_path(input_obj.get("path"))
    fp.parent.mkdir(parents=True, exist_ok=True)
    content = input_obj.get("content") or ""
    mode = input_obj.get("mode")
    if mode == "append" and fp.exists():
        with fp.open("a", encoding="utf-8") as handle:
            handle.write(content)
    else:
        fp.write_text(content, encoding="utf-8")
    byte_len = len(content.encode("utf-8"))
    return f"wrote {byte_len} bytes to {fp.relative_to(WORKDIR)}"


def run_edit(input_obj: Dict[str, Any]) -> str:
    fp = safe_path(input_obj.get("path"))
    text = fp.read_text("utf-8")
    action = input_obj.get("action")

    if action == "replace":
        find = str(input_obj.get("find") or "")
        if not find:
            raise ValueError("edit_text.replace missing find")
        replaced = text.replace(find, str(input_obj.get("replace") or ""))
        fp.write_text(replaced, encoding="utf-8")
        return f"replace done ({len(replaced.encode('utf-8'))} bytes)"

    if action == "insert":
        line_number = int(input_obj.get("insert_after") if input_obj.get("insert_after") is not None else -1)
        rows = text.split("\n")
        idx = max(-1, min(len(rows) - 1, line_number))
        rows[idx + 1: idx + 1] = [str(input_obj.get("new_text") or "")]
        updated = "\n".join(rows)
        fp.write_text(updated, encoding="utf-8")
        return f"inserted after line {line_number}"

    if action == "delete_range":
        target_range = input_obj.get("range") or []
        if not (
            len(target_range) == 2
            and isinstance(target_range[0], int)
            and isinstance(target_range[1], int)
            and target_range[1] >= target_range[0]
        ):
            raise ValueError("edit_text.delete_range invalid range")
        start, end = target_range
        rows = text.split("\n")
        updated = "\n".join([*rows[:start], *rows[end:]])
        fp.write_text(updated, encoding="utf-8")
        return f"deleted lines [{start}, {end})"

    raise ValueError(f"unsupported edit_text.action: {action}")


def run_todo_update(input_obj: Dict[str, Any]) -> str:
    board_view = TODO_BOARD.update(input_obj.get("items") or [])
    AGENT_STATE["rounds_without_todo"] = 0
    stats = TODO_BOARD.stats()
    if stats["total"] == 0:
        summary = "No todos have been created."
    else:
        summary = (
            f"Status updated: {stats['completed']} completed, "
            f"{stats['in_progress']} in progress."
        )
    return board_view + ("\n\n" + summary if summary else "")


def dispatch_tool(tool_use: Dict[str, Any]) -> Dict[str, Any]:
    def get_value(obj: Any, key: str, default: Any = None) -> Any:
        return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)

    name = get_value(tool_use, "name")
    input_obj = get_value(tool_use, "input", {}) or {}
    tool_use_id = get_value(tool_use, "id")

    try:
        if name == "bash":
            pretty_tool_line("Bash", input_obj.get("command") if isinstance(input_obj, dict) else None)
            result = run_bash(input_obj if isinstance(input_obj, dict) else {})
            pretty_sub_line(clamp_text(result, 2000) if result else "(no content)")
            return {"type": "tool_result", "tool_use_id": tool_use_id, "content": result}

        if name == "read_file":
            pretty_tool_line("Read", input_obj.get("path") if isinstance(input_obj, dict) else None)
            result = run_read(input_obj if isinstance(input_obj, dict) else {})
            pretty_sub_line(clamp_text(result, 2000))
            return {"type": "tool_result", "tool_use_id": tool_use_id, "content": result}

        if name == "write_file":
            pretty_tool_line("Write", input_obj.get("path") if isinstance(input_obj, dict) else None)
            result = run_write(input_obj if isinstance(input_obj, dict) else {})
            pretty_sub_line(result)
            return {"type": "tool_result", "tool_use_id": tool_use_id, "content": result}

        if name == "edit_text":
            action = input_obj.get("action") if isinstance(input_obj, dict) else None
            path_value = input_obj.get("path") if isinstance(input_obj, dict) else None
            pretty_tool_line("Edit", f"{action} {path_value}")
            result = run_edit(input_obj if isinstance(input_obj, dict) else {})
            pretty_sub_line(result)
            return {"type": "tool_result", "tool_use_id": tool_use_id, "content": result}

        if name == "TodoWrite":
            pretty_tool_line("Update Todos", "{ params.todo }")
            result = run_todo_update(input_obj if isinstance(input_obj, dict) else {})
            pretty_sub_line(result)
            return {"type": "tool_result", "tool_use_id": tool_use_id, "content": result}

        message = f"unknown tool: {name}"
        return {"type": "tool_result", "tool_use_id": tool_use_id, "content": message, "is_error": True}

    except Exception as error:  # pragma: no cover - runtime error path
        return {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": str(error),
            "is_error": True,
        }


def query(messages: List[Dict[str, Any]], opts: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
    opts = opts or {}
    while True:
        spinner = Spinner()
        spinner.start()
        try:
            response = client.messages.create(
                model=AGENT_MODEL,
                system=SYSTEM,
                messages=messages,
                tools=tools,
                max_tokens=16000,
                **({"tool_choice": opts["tool_choice"]} if "tool_choice" in opts else {}),
            )
        finally:
            spinner.stop()

        tool_uses: List[Any] = []
        try:
            for block in getattr(response, "content", []) or []:
                block_type = getattr(block, "type", None) if not isinstance(block, dict) else block.get("type")
                if block_type == "text":
                    text_value = getattr(block, "text", None) if not isinstance(block, dict) else block.get("text")
                    sys.stdout.write(format_markdown(text_value or "") + "\n")
                if block_type == "tool_use":
                    tool_uses.append(block)
        except Exception as err:
            log_error_debug(
                "Iterating response content failed",
                {
                    "error": str(err),
                    "stop_reason": getattr(response, "stop_reason", None),
                    "content_type": type(getattr(response, "content", None)).__name__,
                },
            )
            raise

        if getattr(response, "stop_reason", None) == "tool_use":
            results = [dispatch_tool(tool_use) for tool_use in tool_uses]
            messages.append({"role": "assistant", "content": normalize_content_list(response.content)})
            messages.append({"role": "user", "content": results})
            continue

        messages.append({"role": "assistant", "content": normalize_content_list(response.content)})
        return messages


def main() -> None:
    clear_screen()
    render_banner("Tiny CC Agent", "todo-enabled")
    print(f"{INFO_COLOR}Workspace: {WORKDIR}{RESET}")
    print(f"{INFO_COLOR}Type \"exit\" or \"quit\" to leave.{RESET}\n")

    history: List[Dict[str, Any]] = []
    while True:
        try:
            line = input(user_prompt_label())
        except EOFError:
            break

        if not line or line.strip().lower() in {"q", "quit", "exit"}:
            break

        print_divider()

        blocks: List[Dict[str, str]] = []
        if PENDING_CONTEXT_BLOCKS:
            blocks.extend(PENDING_CONTEXT_BLOCKS)
            PENDING_CONTEXT_BLOCKS.clear()

        blocks.append({"type": "text", "text": line})
        history.append({"role": "user", "content": blocks})

        try:
            query(history)
        except Exception as error:
            print(f"{ACCENT_COLOR}Error{RESET}: {str(error)}")

        AGENT_STATE["rounds_without_todo"] += 1
        if AGENT_STATE["rounds_without_todo"] > 10:
            ensure_context_block(NAG_REMINDER)


if __name__ == "__main__":
    main()