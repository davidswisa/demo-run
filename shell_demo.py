#!/usr/bin/env python3
"""Interactive demo: navigate shell commands with arrows, run with Enter."""

import curses
import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Callable, Optional


def load_env(path: str | Path) -> dict[str, str]:
    """Parse a minimal KEY=VALUE .env file; ignores blanks and # comments."""
    variables: dict[str, str] = {}
    for raw in Path(path).read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        variables[key.strip()] = value
    return variables


@dataclass
class Command:
    description: str
    command: str
    # post(output, variables) -> optional display string; may mutate variables.
    post: Optional[Callable[[str, dict[str, str]], Optional[str]]] = None


def render(cmd: str, variables: dict[str, str]) -> str:
    return Template(cmd).safe_substitute(variables)


def run(cmd: str) -> tuple[str, int]:
    """Execute ``cmd`` and return (combined_output, returncode).

    Multiline commands (e.g. heredocs) are run through the shell; single-line
    commands are split with shlex to avoid an unnecessary shell wrapper.
    """
    if "\n" in cmd:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    else:
        result = subprocess.run(shlex.split(cmd), capture_output=True, text=True)
    output = result.stdout
    if result.stderr:
        output += ("\n" if output and not output.endswith("\n") else "") + result.stderr
    return output, result.returncode


def _init_colors() -> dict[str, int]:
    """Initialise color pairs and return a name->attr mapping."""
    if not curses.has_colors():
        return {k: 0 for k in ("title", "desc", "prompt", "cmd", "border", "label", "ok", "err", "dim", "extract")}
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_CYAN, -1)
    curses.init_pair(2, curses.COLOR_YELLOW, -1)
    curses.init_pair(3, curses.COLOR_GREEN, -1)
    curses.init_pair(4, curses.COLOR_RED, -1)
    curses.init_pair(5, curses.COLOR_MAGENTA, -1)
    curses.init_pair(6, curses.COLOR_BLUE, -1)
    return {
        "title": curses.color_pair(1) | curses.A_BOLD,
        "desc": curses.color_pair(2) | curses.A_BOLD,
        "prompt": curses.color_pair(3) | curses.A_BOLD,
        "cmd": curses.A_BOLD,
        "border": curses.color_pair(6),
        "label": curses.color_pair(1) | curses.A_BOLD,
        "ok": curses.color_pair(3) | curses.A_BOLD,
        "err": curses.color_pair(4) | curses.A_BOLD,
        "dim": curses.A_DIM,
        "extract": curses.color_pair(5) | curses.A_BOLD,
    }


def _safe_addnstr(stdscr, row: int, col: int, text: str, n: int, attr: int) -> None:
    # Writing to the bottom-right cell always errors in curses; swallow it.
    try:
        stdscr.addnstr(row, col, text, n, attr)
    except curses.error:
        pass


def _hline(stdscr, row: int, width: int, attr: int, left: str = "├", right: str = "┤") -> None:
    _safe_addnstr(stdscr, row, 0, left + "─" * (width - 2) + right, width, attr)


def _draw(stdscr, commands, variables, selected, output_lines, status, status_attr, colors):
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    w = max(w, 20)

    # top border + title
    _safe_addnstr(stdscr, 0, 0, "╭" + "─" * (w - 2) + "╮", w, colors["border"])
    title = " Shell demo — ↑/↓ navigate  ↵ run  q quit "
    _safe_addnstr(stdscr, 0, max(2, (w - len(title)) // 2), title, w - 4, colors["title"])

    # command panel
    item = commands[selected]
    pos = f" {selected + 1}/{len(commands)} "
    _safe_addnstr(stdscr, 1, 0, "│", 1, colors["border"])
    _safe_addnstr(stdscr, 1, w - 1, "│", 1, colors["border"])
    _safe_addnstr(stdscr, 1, 2, "DESCRIPTION", w - 4, colors["label"])
    _safe_addnstr(stdscr, 1, w - len(pos) - 2, pos, len(pos), colors["dim"])

    _safe_addnstr(stdscr, 2, 0, "│", 1, colors["border"])
    _safe_addnstr(stdscr, 2, w - 1, "│", 1, colors["border"])
    _safe_addnstr(stdscr, 2, 4, item.description[: w - 6], w - 6, colors["desc"])

    _hline(stdscr, 3, w, colors["border"])

    _safe_addnstr(stdscr, 4, 0, "│", 1, colors["border"])
    _safe_addnstr(stdscr, 4, w - 1, "│", 1, colors["border"])
    _safe_addnstr(stdscr, 4, 2, "COMMAND", w - 4, colors["label"])

    rendered = render(item.command, variables)
    cmd_lines = rendered.splitlines() or [""]
    for i, line in enumerate(cmd_lines):
        row = 5 + i
        _safe_addnstr(stdscr, row, 0, "│", 1, colors["border"])
        _safe_addnstr(stdscr, row, w - 1, "│", 1, colors["border"])
        # Only the first line gets the "$ " prompt; continuation lines are indented.
        prompt = "$" if i == 0 else " "
        _safe_addnstr(stdscr, row, 4, prompt, 1, colors["prompt"])
        _safe_addnstr(stdscr, row, 6, line[: w - 8], w - 8, colors["cmd"])

    cmd_end = 5 + len(cmd_lines)  # first row after the command block

    # status bar
    _hline(stdscr, cmd_end, w, colors["border"])
    _safe_addnstr(stdscr, cmd_end + 1, 0, "│", 1, colors["border"])
    _safe_addnstr(stdscr, cmd_end + 1, w - 1, "│", 1, colors["border"])
    _safe_addnstr(stdscr, cmd_end + 1, 2, "STATUS", w - 4, colors["label"])
    _safe_addnstr(stdscr, cmd_end + 1, 10, status[: w - 12], w - 12, status_attr)

    # output panel
    _hline(stdscr, cmd_end + 2, w, colors["border"])
    _safe_addnstr(stdscr, cmd_end + 3, 0, "│", 1, colors["border"])
    _safe_addnstr(stdscr, cmd_end + 3, w - 1, "│", 1, colors["border"])
    _safe_addnstr(stdscr, cmd_end + 3, 2, "OUTPUT", w - 4, colors["label"])

    out_start = cmd_end + 4
    max_out = h - out_start - 1
    if max_out > 0:
        visible = output_lines[-max_out:]
        for i in range(max_out):
            row = out_start + i
            _safe_addnstr(stdscr, row, 0, "│", 1, colors["border"])
            _safe_addnstr(stdscr, row, w - 1, "│", 1, colors["border"])
            if i < len(visible):
                line = visible[i]
                attr = curses.A_NORMAL
                if line.startswith("$ "):
                    _safe_addnstr(stdscr, row, 2, "$", 1, colors["prompt"])
                    _safe_addnstr(stdscr, row, 4, line[2:][: w - 6], w - 6, colors["cmd"])
                    continue
                if line.startswith("  "):
                    # Continuation of a multi-line command; keep the cmd styling aligned.
                    _safe_addnstr(stdscr, row, 4, line[2:][: w - 6], w - 6, colors["cmd"])
                    continue
                if line.startswith("extracted:"):
                    attr = colors["extract"]
                _safe_addnstr(stdscr, row, 2, line[: w - 4], w - 4, attr)

    # bottom border (write left corner + line, then last corner via insstr to dodge the
    # ERR you get when addnstr writes into the bottom-right cell)
    _safe_addnstr(stdscr, h - 1, 0, "╰" + "─" * (w - 2), w - 1, colors["border"])
    try:
        stdscr.insstr(h - 1, w - 1, "╯", colors["border"])
    except curses.error:
        pass

    stdscr.refresh()


def interactive(stdscr, commands: list[Command], variables: dict[str, str]) -> None:
    curses.curs_set(0)
    stdscr.keypad(True)
    colors = _init_colors()

    selected = 0
    output_lines: list[str] = []
    status = "Ready."
    status_attr = colors["dim"]

    while True:
        _draw(stdscr, commands, variables, selected, output_lines, status, status_attr, colors)
        key = stdscr.getch()

        if key in (curses.KEY_UP, ord("k")):
            selected = max(0, selected - 1)
        elif key in (curses.KEY_DOWN, ord("j")):
            selected = min(len(commands) - 1, selected + 1)
        elif key in (curses.KEY_ENTER, 10, 13):
            item = commands[selected]
            cmd = render(item.command, variables)
            status = f"Running: {cmd}"
            status_attr = colors["title"]
            _draw(stdscr, commands, variables, selected, output_lines, status, status_attr, colors)
            output, rc = run(cmd)
            cmd_lines = cmd.splitlines() or [""]
            output_lines = [f"$ {cmd_lines[0]}"] + [f"  {ln}" for ln in cmd_lines[1:]]
            output_lines += output.splitlines()
            if item.post is not None:
                try:
                    extracted = item.post(output, variables)
                except Exception as exc:
                    extracted = f"<post error: {exc}>"
                if extracted:
                    output_lines += ["", f"extracted: {extracted}"]
            status = f"exit {rc}  ✓" if rc == 0 else f"exit {rc}  ✗"
            status_attr = colors["ok"] if rc == 0 else colors["err"]
        elif key in (ord("q"), 27):
            break


if __name__ == "__main__":
    variables = load_env(Path(__file__).with_name(".env"))

    commands = [
        Command(
            description="List current log levels",
            command="kubectl get loglevel -n $NAMESPACE",
        ),
        Command(
            description="Get a pod log levels",
            command="kubectl get loglevel $NAME -n $NAMESPACE",
        ),
        Command(
            description=f"Set log level of $CONTAINER to $LEVEL using replace",
            command='''kubectl replace -f - <<EOF
apiVersion: ops.f5net.com/v1alpha1
kind: LogLevel
metadata:
  name: $NAME
  namespace: $NAMESPACE
spec:
  containers:
    $CONTAINER:
      level: $LEVEL
EOF''',
        ),
        Command(
            description="list log levels to verify the change",
            command="kubectl get loglevel -n $NAMESPACE",
        ),
        Command(
            description=f"ReSet log level of $CONTAINER to DEFAULT",
            command="kubectl delete loglevel $NAME -n $NAMESPACE",
        ),
        Command(
            description="List log levels to verify the reset",
            command="kubectl get loglevel -n $NAMESPACE",
        ),
        Command(
            description="f5ops plugin - List log levels to verify the change",
            command="kubectl f5ops loglevel list -n $NAMESPACE",
        ),
        Command(
            description="f5ops plugin - Get log levels to verify the change",
            command="kubectl f5ops loglevel get $NAME -n $NAMESPACE",
        ),
        Command(
            description=f"f5ops plugin - Set log level of $CONTAINER to $LEVEL",
            command="kubectl f5ops loglevel set $NAME $CONTAINER $LEVEL -n $NAMESPACE",
        ),
        Command(
            description="f5ops plugin - List log levels to verify the change",
            command="kubectl f5ops loglevel list -n $NAMESPACE",
        ),
        Command(
            description=f"f5ops plugin - ReSet log level of $CONTAINER to DEFAULT",
            command="kubectl f5ops loglevel reset $NAME -n $NAMESPACE",
        ),
        Command(
            description="f5ops plugin - List log levels to verify the reset",
            command="kubectl f5ops loglevel list -n $NAMESPACE",
        ),

        Command(
            description="create a qkview",
            command="kubectl f5ops qkview create",
            post=lambda out, v: (
                v.update(QKVIEW_ID=m.group(0)) or f"QKVIEW_ID = {m.group(0)}"
                if (m := re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", out))
                else "<no qkview id found in output>"
            ),
        ),
        Command(
            description="get qkview",
            command="kubectl f5ops qkview get $QKVIEW_ID",
        ),
    ]

    curses.wrapper(interactive, commands, variables)
