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


@dataclass(kw_only=True)
class Command:
    title: str
    note: str = ""
    command: str
    # post(output, variables) -> optional display string; may mutate variables.
    post: Optional[Callable[[str, dict[str, str]], Optional[str]]] = None
    # When True, Enter shows the rendered command but does not execute it.
    dontExecute: bool = False
    # Group label used to bucket commands into scenarios (←/→ to switch).
    scenario: str = ""


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
        return {k: 0 for k in ("title", "desc", "prompt", "cmd", "border", "label", "ok", "err", "dim", "extract", "info")}
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
        "info": curses.color_pair(6) | curses.A_BOLD,
    }


def _safe_addnstr(stdscr, row: int, col: int, text: str, n: int, attr: int) -> None:
    # Writing to the bottom-right cell always errors in curses; swallow it.
    try:
        stdscr.addnstr(row, col, text, n, attr)
    except curses.error:
        pass


def _hline(stdscr, row: int, width: int, attr: int, left: str = "├", right: str = "┤") -> None:
    _safe_addnstr(stdscr, row, 0, left + "─" * (width - 2) + right, width, attr)


def _draw(stdscr, commands, variables, selected, output_lines, output_offset, status, status_attr, colors, scenario_label=""):
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    w = max(w, 20)

    # top border + title
    _safe_addnstr(stdscr, 0, 0, "╭" + "─" * (w - 2) + "╮", w, colors["border"])
    scenario_part = f" ◀ {scenario_label} ▶ —" if scenario_label else ""
    title = f" Shell demo{scenario_part} ↑↓ nav  ←→ scenario  ⭵ run  c clear  PgUp/PgDn scroll  q quit "
    _safe_addnstr(stdscr, 0, max(2, (w - len(title)) // 2), title, w - 4, colors["title"])

    # command panel
    item = commands[selected]
    pos = f" {selected + 1}/{len(commands)} "
    _safe_addnstr(stdscr, 1, 0, "│", 1, colors["border"])
    _safe_addnstr(stdscr, 1, w - 1, "│", 1, colors["border"])
    _safe_addnstr(stdscr, 1, 2, "TITLE", w - 4, colors["label"])
    _safe_addnstr(stdscr, 1, w - len(pos) - 2, pos, len(pos), colors["dim"])

    _safe_addnstr(stdscr, 2, 0, "│", 1, colors["border"])
    _safe_addnstr(stdscr, 2, w - 1, "│", 1, colors["border"])
    _safe_addnstr(stdscr, 2, 4, render(item.title, variables)[: w - 6], w - 6, colors["desc"])

    _hline(stdscr, 3, w, colors["border"])

    row = 4
    if item.note:
        _safe_addnstr(stdscr, row, 0, "│", 1, colors["border"])
        _safe_addnstr(stdscr, row, w - 1, "│", 1, colors["border"])
        _safe_addnstr(stdscr, row, 2, "NOTE", w - 4, colors["label"])
        row += 1
        for line in render(item.note, variables).splitlines() or [""]:
            _safe_addnstr(stdscr, row, 0, "│", 1, colors["border"])
            _safe_addnstr(stdscr, row, w - 1, "│", 1, colors["border"])
            _safe_addnstr(stdscr, row, 4, line[: w - 6], w - 6, colors["info"])
            row += 1
        _hline(stdscr, row, w, colors["border"])
        row += 1

    _safe_addnstr(stdscr, row, 0, "│", 1, colors["border"])
    _safe_addnstr(stdscr, row, w - 1, "│", 1, colors["border"])
    _safe_addnstr(stdscr, row, 2, "COMMAND", w - 4, colors["label"])
    row += 1

    rendered = render(item.command, variables)
    cmd_lines = rendered.splitlines() or [""]
    for i, line in enumerate(cmd_lines):
        _safe_addnstr(stdscr, row, 0, "│", 1, colors["border"])
        _safe_addnstr(stdscr, row, w - 1, "│", 1, colors["border"])
        # Only the first line gets the "$ " prompt; continuation lines are indented.
        prompt = "$" if i == 0 else " "
        _safe_addnstr(stdscr, row, 4, prompt, 1, colors["prompt"])
        _safe_addnstr(stdscr, row, 6, line[: w - 8], w - 8, colors["cmd"])
        row += 1

    cmd_end = row  # first row after the command block

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
        total = len(output_lines)
        scrollable = total > max_out
        max_offset = max(0, total - max_out)
        offset = max(0, min(output_offset, max_offset))
        start = max(0, total - max_out - offset)
        visible = output_lines[start : start + max_out]
        for i in range(max_out):
            row = out_start + i
            _safe_addnstr(stdscr, row, 0, "│", 1, colors["border"])
            if not scrollable:
                _safe_addnstr(stdscr, row, w - 1, "│", 1, colors["border"])
            if i < len(visible):
                line = visible[i]
                attr = curses.A_NORMAL
                # Reserve one column for the scrollbar/border on the right.
                content_w = w - 5
                if line.startswith("$ "):
                    _safe_addnstr(stdscr, row, 2, "$", 1, colors["prompt"])
                    _safe_addnstr(stdscr, row, 4, line[2:][:content_w - 1], content_w - 1, colors["cmd"])
                    continue
                if line.startswith("  "):
                    # Continuation of a multi-line command; keep the cmd styling aligned.
                    _safe_addnstr(stdscr, row, 4, line[2:][:content_w - 1], content_w - 1, colors["cmd"])
                    continue
                if line.startswith("extracted:"):
                    attr = colors["extract"]
                _safe_addnstr(stdscr, row, 2, line[:content_w + 1], content_w + 1, attr)

        if scrollable:
            # Thumb sized proportionally; offset==0 pins it to the bottom.
            thumb = max(1, (max_out * max_out) // total)
            free = max_out - thumb
            thumb_top = free - round((offset / max_offset) * free) if max_offset else free
            for i in range(max_out):
                row = out_start + i
                if thumb_top <= i < thumb_top + thumb:
                    _safe_addnstr(stdscr, row, w - 1, "█", 1, colors["prompt"])
                else:
                    _safe_addnstr(stdscr, row, w - 1, "░", 1, colors["dim"])

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

    # Preserve first-seen order of scenarios so navigation is predictable.
    scenarios = list(dict.fromkeys(c.scenario for c in commands)) or [""]
    scenario_idx = 0
    selected = 0
    output_lines: list[str] = []
    output_offset = 0  # lines scrolled up from the bottom; 0 pins to newest.
    status = "Ready."
    status_attr = colors["dim"]

    while True:
        current_scenario = scenarios[scenario_idx]
        visible = [c for c in commands if c.scenario == current_scenario]
        if not visible:
            visible = commands
        selected = min(selected, len(visible) - 1)
        scenario_name = current_scenario or "(default)"
        scenario_label = f"{scenario_idx + 1}/{len(scenarios)}: {scenario_name}"

        _draw(stdscr, visible, variables, selected, output_lines, output_offset, status, status_attr, colors, scenario_label)
        key = stdscr.getch()

        if key in (curses.KEY_UP, ord("k")):
            selected = max(0, selected - 1)
        elif key in (curses.KEY_DOWN, ord("j")):
            selected = min(len(visible) - 1, selected + 1)
        elif key in (curses.KEY_LEFT, ord("h")):
            if scenario_idx > 0:
                scenario_idx -= 1
                selected = 0
                output_offset = 0
        elif key in (curses.KEY_RIGHT, ord("l")):
            if scenario_idx < len(scenarios) - 1:
                scenario_idx += 1
                selected = 0
                output_offset = 0
        elif key == curses.KEY_PPAGE:
            output_offset = min(output_offset + 10, len(output_lines))
        elif key == curses.KEY_NPAGE:
            output_offset = max(output_offset - 10, 0)
        elif key == curses.KEY_HOME:
            output_offset = len(output_lines)
        elif key == curses.KEY_END:
            output_offset = 0
        elif key == ord("c"):
            output_lines = []
            output_offset = 0
            status = "Output cleared."
            status_attr = colors["dim"]
        elif key in (curses.KEY_ENTER, 10, 13):
            item = visible[selected]
            cmd = render(item.command, variables)
            output_offset = 0
            cmd_lines = cmd.splitlines() or [""]
            if item.dontExecute:
                output_lines = [f"$ {cmd_lines[0]}"] + [f"  {ln}" for ln in cmd_lines[1:]]
                output_lines += ["", "<skipped: dontExecute=True>"]
                status = "Skipped (dontExecute)"
                status_attr = colors["dim"]
                continue
            status = f"Running: {cmd.splitlines()[0]}"
            status_attr = colors["title"]
            _draw(stdscr, visible, variables, selected, output_lines, output_offset, status, status_attr, colors, scenario_label)
            output, rc = run(cmd)
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
    # Log Level Demo

    LOGLEVEL_APPLY_YAML = '''kubectl apply -f - <<EOF
apiVersion: ops.f5net.com/v1alpha1
kind: LogLevel
metadata: 
  name: $NAME
  namespace: $NAMESPACE
spec:
  containers:
    - name: $CONTAINER
      level: $LEVEL
EOF'''

    QKVIEW_CANCEL_FLOW_CREATE_YAML = '''kubectl create -f - <<'EOF'
apiVersion: ops.f5net.com/v1alpha1
kind: Qkview
metadata:
  generateName: qkview-
spec:
  filename: my-qkview-cancel-flow
  description: "Ad-hoc diagnostic collection"
  timeout: "120s"
  podPatterns:
    - "tmm-*"
EOF'''

    QKVIEW_FLOW_CREATE_YAML = '''kubectl create -f - <<'EOF'
apiVersion: ops.f5net.com/v1alpha1
kind: Qkview
metadata:
  generateName: qkview-
spec:
  filename: my-qkview
  description: "Ad-hoc diagnostic collection"
  timeout: "120s"
  podPatterns:
    - "tmm-*"
EOF'''

    commands = [
        Command(
            scenario="Log Level",
            title="List current log levels",
            command="kubectl get loglevel -n $NAMESPACE",
        ),
        Command(
            scenario="Log Level",
            title="Get a pod log levels",
            command="kubectl get loglevel $NAME -n $NAMESPACE",
        ),
        Command(
            scenario="Log Level",
            title="Get log levels resource to show initial state",
            command="kubectl get loglevel $NAME -n $NAMESPACE -oyaml",
        ),
        Command(
            scenario="Log Level",
            title=f"Set log level of $CONTAINER to $LEVEL using replace",
            command=LOGLEVEL_APPLY_YAML,
        ),
        Command(
            scenario="Log Level",
            title="Get log levels resource after the change",
            command="kubectl get loglevel $NAME -n $NAMESPACE -oyaml",
        ),
        Command(
            scenario="Log Level",
            title="List log levels to verify the change",
            command="kubectl get loglevel -n $NAMESPACE",
        ),
        Command(
            scenario="Log Level",
            title=f"ReSet log level of $CONTAINER to DEFAULT",
            command="kubectl delete loglevel $NAME -n $NAMESPACE",
        ),
        Command(
            scenario="Log Level",
            title="List log levels to verify the reset",
            command="kubectl get loglevel -n $NAMESPACE",
        ),

        Command(
            scenario="f5ops plugin",
            title="List log levels to verify the change",
            command="kubectl f5ops loglevel list -n $NAMESPACE",
        ),
        Command(
            scenario="f5ops plugin",
            title="Get log levels to verify the change",
            command="kubectl f5ops loglevel get $NAME -n $NAMESPACE",
        ),
        Command(
            scenario="f5ops plugin",
            title=f"Set log level of $CONTAINER to $LEVEL",
            note='''This command simplifies the pure kuberneties command:\n''' + LOGLEVEL_APPLY_YAML,
            command="kubectl f5ops loglevel set $NAME $CONTAINER $LEVEL -n $NAMESPACE",
        ),
        Command(
            scenario="f5ops plugin",
            title="List log levels to verify the change",
            command="kubectl f5ops loglevel list -n $NAMESPACE",
        ),
        Command(
            scenario="f5ops plugin",
            title=f"ReSet log level of $CONTAINER to DEFAULT",
            command="kubectl f5ops loglevel reset $NAME -n $NAMESPACE",
        ),
        Command(
            scenario="f5ops plugin",
            title="List log levels to verify the reset",
            command="kubectl f5ops loglevel list -n $NAMESPACE",
        ),
        Command(
            scenario="EDIT",
            title=f"Set log level of $CONTAINER to NOTICE",
            command="kubectl f5ops loglevel set $NAME $CONTAINER NOTICE -n $NAMESPACE",
        ),
        Command(
            scenario="EDIT",
            title="List log levels to verify the reset",
            command="kubectl f5ops loglevel list -n $NAMESPACE",
        ),
        Command(
            scenario="EDIT",
            title=f"Set log level of $CONTAINER2 to NOTICE",
            command="kubectl f5ops loglevel set $NAME $CONTAINER2 ERROR -n $NAMESPACE",
        ),
        Command(
            scenario="EDIT",
            title="List log levels to verify the reset",
            command="kubectl f5ops loglevel list -n $NAMESPACE",
        ),
        Command(
            scenario="EDIT",
            title=f"Edit log level resource directly",
            command="kubectl edit loglevel $NAME -n $NAMESPACE",
            dontExecute=True,
        ),
        Command(
            scenario="EDIT",
            title="List log levels to verify the reset",
            command="kubectl f5ops loglevel list -n $NAMESPACE",
        ),
        Command(
            scenario="EDIT",
            title=f"Edit log level resource directly using f5ops plugin",
            command="kubectl f5ops loglevel edit $NAME -n $NAMESPACE",
            dontExecute=True,
        ),
        Command(
            scenario="EDIT",
            title="List log levels to verify the reset",
            command="kubectl f5ops loglevel list -n $NAMESPACE",
        ),
        Command(
            scenario="EDIT",
            title=f"ReSet log level of $CONTAINER to DEFAULT",
            command="kubectl f5ops loglevel reset $NAME -n $NAMESPACE",
        ),
        # Nostdout Demo

        Command(
            scenario="NoStdout",
            title="Monitor log level resource on changes",
            note='''At the request of BNPP, the nostdout field was introduced to suppress log outputs to the standard output stream.''',
            command="watch -d -n 0.5 kubectl f5ops loglevel get $NAME -n $NAMESPACE -oyaml",
            dontExecute=True,
        ),
        Command(
            scenario="NoStdout",
            title=f"Set log level of $CONTAINER to DEBUG",
            command="kubectl f5ops loglevel set $NAME $CONTAINER DEBUG -n $NAMESPACE",
        ),
        Command(
            scenario="NoStdout",
            title=f"Set NoStdout for resource",
            command="kubectl patch loglevel $NAME -n $NAMESPACE -p '{\"spec\":{\"containers\":[{\"name\":\"$CONTAINER\",\"nostdout\":\"ENABLED\"}]}}'",
        ),

        Command(
            scenario="NoStdout",
            title=f"Set NoStdout for resource",
            command="kubectl f5ops loglevel patch $NAME -n $NAMESPACE -p '{\"spec\":{\"containers\":[{\"name\":\"$CONTAINER\",\"nostdout\":\"DISABLED\"}]}}'",
        ),
        Command(
            scenario="NoStdout",
            title=f"ReSet log level of $CONTAINER to DEFAULT",
            command="kubectl f5ops loglevel reset $NAME -n $NAMESPACE",
        ),

        # Qkview Demo
        Command(
            scenario="Qkview",
            title="List qkview with watch",
            command="kubectl get qkviews -w",
            dontExecute=True,
        ),
        Command(
            scenario="Qkview",
            title="List qkview",
            command="kubectl get qkviews",
        ),
        Command(
            scenario="Qkview",
            title="Create a qkview",
            # metion the previously there was a REST to CWC with token which was less user friendly
            command=QKVIEW_FLOW_CREATE_YAML,
            post=lambda out, v: (
                v.update(QKVIEW_ID=m.group(0)) or f"QKVIEW_ID = {m.group(0)}"
                if (m := re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", out))
                else "<no qkview id found in output>"
            ),
        ),
        Command(
            scenario="Qkview",
            title="Get the created qkview",
            command="kubectl get qkviews $QKVIEW_ID",
        ),
        Command(
            scenario="Qkview",
            title="Get qkview content in yaml format",
            command="kubectl get qkviews $QKVIEW_ID -oyaml",
        ),
        Command(
            scenario="Qkview",
            title="Get qkview status in yaml format",
            note='''The status subresource provides information about the current state of the qkview resource, 
including all subtasks progress and any errors encountered during the collection process.''',
            command="kubectl get qkviews --subresource=status $QKVIEW_ID -oyaml",
        ),
        Command(
            scenario="Qkview",
            title="List qkview with filename filter",
            command="kubectl get qkviews --field-selector=filename=my-qkview",
        ),
        Command(
            scenario="Qkview",
            title="Create a qkview for cancel flow",
            command=QKVIEW_CANCEL_FLOW_CREATE_YAML,
            post=lambda out, v: (
                v.update(QKVIEW_ID=m.group(0)) or f"QKVIEW_ID = {m.group(0)}"
                if (m := re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", out))
                else "<no qkview id found in output>"
            ),
        ),
        Command(
            scenario="Qkview",
            title="Cancel qkview",
            command='''kubectl create --raw "/apis/ops.f5net.com/v1alpha1/qkviews/$QKVIEW_ID/cancel" -f - <<'EOF'     
{}
EOF''',
        ),

        Command(
            scenario="Qkview with f5ops plugin",
            title="List qkview",
            command="kubectl f5ops qkview list",
        ),
        Command(
            scenario="Qkview with f5ops plugin",
            title="Create a qkview",
            note='''The f5ops plugin simplifies the creation of a qkview resource by providing a more user-friendly command.\n''' + QKVIEW_FLOW_CREATE_YAML,
            command="kubectl f5ops qkview create --filename my-qkview-f5ops",
            post=lambda out, v: (
                v.update(QKVIEW_ID=m.group(0)) or f"QKVIEW_ID = {m.group(0)}"
                if (m := re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", out))
                else "<no qkview id found in output>"
            ),
        ),
        Command(
            scenario="Qkview with f5ops plugin",
            title="Get qkview content",
            command="kubectl f5ops qkview get $QKVIEW_ID",
        ),
        Command(
            scenario="Qkview with f5ops plugin",
            title="Get qkview status",
            command="kubectl f5ops qkview status $QKVIEW_ID",
        ),

        Command(
            scenario="Qkview with f5ops plugin",
            note='''The f5ops plugin simplifies the download of a qkview file by providing a more user-friendly command.
kubectl get --raw "/apis/ops.f5net.com/v1alpha1/qkviews/$QKVIEW_ID/download"''',
            title="Get download qkview",
            command="kubectl f5ops qkview download $QKVIEW_ID",
            post=lambda out, v: (
                v.update(QKVIEW_FILE=m.group(1)) or f"QKVIEW_FILE = {m.group(1)}"
                if (m := re.search(r"File path:\s*(\S+)", out))
                else "<no file path found in output>"
            ),
        ),
        Command(
            scenario="Qkview with f5ops plugin",
            title="View Qkview file in file system",
            command="ls -l $QKVIEW_FILE",
        ),
        Command(
            scenario="Qkview with f5ops plugin",
            title="List qkview with filename filter",
            command="kubectl f5ops qkview list --filename=my-qkview-f5ops",
        ),

        Command(
            scenario="Qkview with f5ops plugin",
            title="Create a qkview for cancel",
            command="kubectl f5ops qkview create --filename my-qkview-for-cancel",
            post=lambda out, v: (
                v.update(QKVIEW_ID=m.group(0)) or f"QKVIEW_ID = {m.group(0)}"
                if (m := re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", out))
                else "<no qkview id found in output>"
            ),
        ),
        Command(
            scenario="Qkview with f5ops plugin",
            title="Cancel qkview",
            note='''The f5ops plugin simplifies the cancellation of a qkview resource by providing a more user-friendly command.
kubectl create --raw "/apis/ops.f5net.com/v1alpha1/qkviews/$QKVIEW_ID/cancel" -f - <<'EOF'     
{}
EOF''',
            command="kubectl f5ops qkview cancel $QKVIEW_ID",
        ),
        Command(
            scenario="Qkview with f5ops plugin",
            title="List qkviews",
            command="kubectl f5ops qkview list",
        ),
        Command(
            scenario="Qkview with f5ops plugin",
            title="Get qkview create help",
            command="kubectl f5ops qkview create --help",
        ),
    ]

    curses.wrapper(interactive, commands, variables)
