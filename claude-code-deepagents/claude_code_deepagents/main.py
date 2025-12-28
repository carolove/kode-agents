#!/usr/bin/env python3
"""Main entry point for claude-code-deepagents."""

import sys
import time
import threading
from pathlib import Path

# Add package root to path for direct script execution
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from claude_code_deepagents.config import load_config, AgentConfig
from claude_code_deepagents.agent import CodingAgentSession


class Spinner:
    """Lightweight waiting indicator."""

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
            sys.stdout.write("\r\x1b[2K")
            sys.stdout.flush()
        except Exception:
            pass


def run_interactive(config: AgentConfig):
    """Run the interactive REPL session.

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

        spinner = Spinner()
        spinner.start()

        try:
            response = session.invoke(line)
            spinner.stop()

            if response:
                print(f"\nAssistant: {response}\n")
        except Exception as e:
            spinner.stop()
            print(f"\nError: {e}\n")


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

