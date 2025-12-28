#!/usr/bin/env python3
import os
import sys
import json
import time
import threading
import subprocess
from pathlib import Path

try:
    from anthropic import Anthropic
except Exception as e:
    sys.stderr.write("Install with: pip install anthropic\n")
    raise

ANTHROPIC_BASE_URL = "https://api.moonshot.cn/anthropic"
ANTHROPIC_API_KEY = "sk-xxx" # 替换为你的key
AGENT_MODEL = "kimi-k2-turbo-preview"

# ---------- Workspace & Helpers ----------
WORKDIR = Path.cwd()
MAX_TOOL_RESULT_CHARS = 100_000


def safe_path(p: str) -> Path:
    abs_path = (WORKDIR / str(p or "")).resolve()
    rel = abs_path.relative_to(WORKDIR) if abs_path.is_relative_to(WORKDIR) else None
    if rel is None:
        raise ValueError("Path escapes workspace")
    return abs_path


def clamp_text(s: str, n: int = MAX_TOOL_RESULT_CHARS) -> str:
    if len(s) <= n:
        return s
    return s[:n] + f"\n\n...<truncated {len(s) - n} chars>"


def pretty_tool_line(kind: str, title: str) -> None:
    print(f"{kind}({title})…")


def pretty_sub_line(text: str) -> None:
    print(f"  ⎿ {text}")


# 轻量等待指示器（最小实现）
class Spinner:
    def __init__(self, label: str = "等待模型响应") -> None:
        self.label = label
        self.frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if not sys.stdout.isatty() or self._thread is not None:
            return
        self._stop.clear()

        def run():
            i = 0
            while not self._stop.is_set():
                sys.stdout.write("\r" + self.label + " " + self.frames[i % len(self.frames)])
                sys.stdout.flush()
                i += 1
                time.sleep(0.08)

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()

    def stop(self):
        if self._thread is None:
            return
        self._stop.set()
        self._thread.join(timeout=1)
        self._thread = None
        try:
            # clear current line
            sys.stdout.write("\r\x1b[2K")
            sys.stdout.flush()
        except Exception:
            pass


def log_error_debug(tag: str, info) -> None:
    try:
        js = json.dumps(info, ensure_ascii=False, indent=2)
        out = js if len(js) <= 4000 else js[:4000] + "\n...<truncated>"
        print(f"⚠️  {tag}:")
        print(out)
    except Exception:
        print(f"⚠️  {tag}: (unserializable info)")


# ---------- Content normalization helpers ----------
def block_to_dict(block):
    """Convert SDK response block objects to plain dicts for reuse in messages.
    Supports TextBlock, ToolUseBlock, and dict inputs. Best-effort fallback.
    """
    if isinstance(block, dict):
        return block
    out = {}
    for key in ("type", "text", "id", "name", "input", "citations"):
        if hasattr(block, key):
            out[key] = getattr(block, key)
    # Fallback: include any public attributes
    if not out and hasattr(block, "__dict__"):
        out = {k: v for k, v in vars(block).items() if not k.startswith("_")}
        if hasattr(block, "type"):
            out["type"] = getattr(block, "type")
    return out


def normalize_content_list(content):
    try:
        return [block_to_dict(b) for b in (content or [])]
    except Exception:
        return []


# ---------- SDK client ----------
api_key = ANTHROPIC_API_KEY
if not api_key:
    sys.stderr.write("❌ ANTHROPIC_API_KEY not set\n")
    sys.exit(1)

base_url = ANTHROPIC_BASE_URL
client = Anthropic(api_key=api_key, base_url=base_url) if base_url else Anthropic(api_key=api_key)


# ---------- System prompt ----------
SYSTEM = (
    f"You are a coding agent operating INSIDE the user's repository at {WORKDIR}.\n"
    "Follow this loop strictly: plan briefly → use TOOLS to act directly on files/shell → report concise results.\n"
    "Rules:\n"
    "- Prefer taking actions with tools (read/write/edit/bash) over long prose.\n"
    "- Keep outputs terse. Use bullet lists / checklists when summarizing.\n"
    "- Never invent file paths. Ask via reads or list directories first if unsure.\n"
    "- For edits, apply the smallest change that satisfies the request.\n"
    "- For bash, avoid destructive or privileged commands; stay inside the workspace.\n"
    "- After finishing, summarize what changed and how to run or test."
)


# ---------- Tools ----------
tools = [
    {
        "name": "bash",
        "description": (
            "Execute a shell command inside the project workspace. Use for scaffolding, "
            "formatting, running scripts, etc."
        ),
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
        "description": "Read a UTF-8 text file. Optionally slice by line range or clamp length.",
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
        "description": "Create or overwrite/append a UTF-8 text file. Use overwrite unless explicitly asked to append.",
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
        "description": "Small, precise text edits. Choose one action: replace | insert | delete_range.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "action": {"type": "string", "enum": ["replace", "insert", "delete_range"]},
                "find": {"type": "string"},
                "replace": {"type": "string"},
                "insert_after": {"type": "integer", "minimum": -1},
                "new_text": {"type": "string"},
                "range": {"type": "array", "items": {"type": "integer"}, "minItems": 2, "maxItems": 2},
            },
            "required": ["path", "action"],
            "additionalProperties": False,
        },
    },
]


# ---------- Tool executors ----------
def run_bash(input_obj: dict) -> str:
    cmd = str(input_obj.get("command") or "")
    if not cmd:
        raise ValueError("missing bash.command")
    if (
        subprocess is not None
        and ("rm -rf /" in cmd or "shutdown" in cmd or "reboot" in cmd or "sudo " in cmd)
    ):
        raise ValueError("blocked dangerous command")
    timeout_ms = int(input_obj.get("timeout_ms") or 30000)
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(WORKDIR),
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout_ms / 1000.0,
        )
        out = "\n".join([x for x in [proc.stdout, proc.stderr] if x]).strip()
        return clamp_text(out or "(no output)")
    except subprocess.TimeoutExpired:
        return "(timeout)"


def run_read(input_obj: dict) -> str:
    fp = safe_path(input_obj.get("path"))
    text = fp.read_text("utf-8")
    lines = text.split("\n")
    start = (max(1, int(input_obj.get("start_line") or 1)) - 1) if input_obj.get("start_line") else 0
    if isinstance(input_obj.get("end_line"), int):
        end_val = input_obj.get("end_line")
        end = len(lines) if end_val < 0 else max(start, end_val)
    else:
        end = len(lines)
    text = "\n".join(lines[start:end])
    max_chars = int(input_obj.get("max_chars") or 100_000)
    return clamp_text(text, max_chars)


def run_write(input_obj: dict) -> str:
    fp = safe_path(input_obj.get("path"))
    fp.parent.mkdir(parents=True, exist_ok=True)
    content = input_obj.get("content") or ""
    mode = input_obj.get("mode")
    if mode == "append" and fp.exists():
        with fp.open("a", encoding="utf-8") as f:
            f.write(content)
    else:
        fp.write_text(content, encoding="utf-8")
    bytes_len = len(content.encode("utf-8"))
    rel = fp.relative_to(WORKDIR)
    return f"wrote {bytes_len} bytes to {rel}"


def run_edit(input_obj: dict) -> str:
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
    elif action == "insert":
        line = int(input_obj.get("insert_after") if input_obj.get("insert_after") is not None else -1)
        lines = text.split("\n")
        idx = max(-1, min(len(lines) - 1, line))
        lines[idx + 1:idx + 1] = [str(input_obj.get("new_text") or "")]
        nxt = "\n".join(lines)
        fp.write_text(nxt, encoding="utf-8")
        return f"inserted after line {line}"
    elif action == "delete_range":
        rng = input_obj.get("range") or []
        if not (len(rng) == 2 and isinstance(rng[0], int) and isinstance(rng[1], int) and rng[1] >= rng[0]):
            raise ValueError("edit_text.delete_range invalid range")
        s, e = rng
        lines = text.split("\n")
        nxt = "\n".join([*lines[:s], *lines[e:]])
        fp.write_text(nxt, encoding="utf-8")
        return f"deleted lines [{s}, {e})"
    else:
        raise ValueError(f"unsupported edit_text.action: {action}")


def dispatch_tool(tu: dict) -> dict:
    try:
        # Support both dict and SDK block objects
        def gv(obj, key, default=None):
            return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)

        name = gv(tu, "name")
        input_obj = gv(tu, "input", {}) or {}
        tool_use_id = gv(tu, "id")

        if name == "bash":
            pretty_tool_line("Bash", (input_obj.get("command") if isinstance(input_obj, dict) else None))
            out = run_bash(input_obj if isinstance(input_obj, dict) else {})
            pretty_sub_line(clamp_text(out, 2000) if out else "(No content)")
            return {"type": "tool_result", "tool_use_id": tool_use_id, "content": out}
        if name == "read_file":
            pretty_tool_line("Read", (input_obj.get("path") if isinstance(input_obj, dict) else None))
            out = run_read(input_obj if isinstance(input_obj, dict) else {})
            pretty_sub_line(clamp_text(out, 2000))
            return {"type": "tool_result", "tool_use_id": tool_use_id, "content": out}
        if name == "write_file":
            pretty_tool_line("Write", (input_obj.get("path") if isinstance(input_obj, dict) else None))
            out = run_write(input_obj if isinstance(input_obj, dict) else {})
            pretty_sub_line(out)
            return {"type": "tool_result", "tool_use_id": tool_use_id, "content": out}
        if name == "edit_text":
            action = input_obj.get("action") if isinstance(input_obj, dict) else None
            path_v = input_obj.get("path") if isinstance(input_obj, dict) else None
            pretty_tool_line("Edit", f"{action} {path_v}")
            out = run_edit(input_obj if isinstance(input_obj, dict) else {})
            pretty_sub_line(out)
            return {"type": "tool_result", "tool_use_id": tool_use_id, "content": out}
        return {"type": "tool_result", "tool_use_id": tool_use_id, "content": f"unknown tool: {name}", "is_error": True}
    except Exception as e:
        tool_use_id = tu.get("id") if isinstance(tu, dict) else getattr(tu, "id", None)
        return {"type": "tool_result", "tool_use_id": tool_use_id, "content": str(e), "is_error": True}


# ---------- Core loop ----------
def query(messages: list, opts: dict | None = None) -> list:
    opts = opts or {}
    while True:
        spinner = Spinner()
        spinner.start()
        try:
            res = client.messages.create(
                model=AGENT_MODEL,
                system=SYSTEM,
                messages=messages,
                tools=tools,
                max_tokens=16000,
                **({"tool_choice": opts["tool_choice"]} if "tool_choice" in opts else {}),
            )
        finally:
            spinner.stop()

        tool_uses = []
        try:
            for block in getattr(res, "content", []):
                btype = getattr(block, "type", None) if not isinstance(block, dict) else block.get("type")
                if btype == "text":
                    text = getattr(block, "text", None) if not isinstance(block, dict) else block.get("text")
                    sys.stdout.write((text or "") + "\n")
                if btype == "tool_use":
                    tool_uses.append(block)
        except Exception as err:
            log_error_debug(
                "Iterating res.content failed",
                {
                    "error": str(err),
                    "stop_reason": getattr(res, "stop_reason", None),
                    "content_type": type(getattr(res, "content", None)).__name__,
                    "is_array": isinstance(getattr(res, "content", None), list),
                    "keys": list(res.__dict__.keys()) if hasattr(res, "__dict__") else [],
                    "preview": (json.dumps(res, default=lambda o: getattr(o, "__dict__", str(o)))[:2000] if res else ""),
                },
            )
            raise

        if getattr(res, "stop_reason", None) == "tool_use":
            results = [dispatch_tool(tu) for tu in tool_uses]
            messages.append({"role": "assistant", "content": normalize_content_list(res.content)})
            messages.append({"role": "user", "content": results})
            continue

        messages.append({"role": "assistant", "content": normalize_content_list(res.content)})
        return messages


def main():
    print(f"Tiny CC Agent (custom tools only) — cwd: {WORKDIR}")
    print('Type "exit" or "quit" to leave.\n')
    history: list = []
    while True:
        try:
            line = input("User: ")
        except EOFError:
            break
        if not line or line.strip().lower() in {"q", "quit", "exit"}:
            break
        history.append({"role": "user", "content": [{"type": "text", "text": line}]})
        try:
            query(history)
        except Exception as e:
            print("Error:", str(e))


if __name__ == "__main__":
    main()