#!/usr/bin/env python3
"""Interactive demo: navigate shell commands with arrows, run with Enter."""

import curses
import re
import shlex
import subprocess
from dataclasses import dataclass
from string import Template
from typing import Callable, Optional


@dataclass
class Command:
    description: str
    command: str
    # post(output, variables) -> optional display string; may mutate variables.
    post: Optional[Callable[[str, dict[str, str]], Optional[str]]] = None


def render(cmd: str, variables: dict[str, str]) -> str:
    return Template(cmd).safe_substitute(variables)


def run(cmd: str) -> tuple[str, int]:
    """Execute ``cmd`` and return (combined_output, returncode)."""
    result = subprocess.run(
        shlex.split(cmd),
        capture_output=True,
        text=True,
    )
    output = result.stdout
    if result.stderr:
        output += ("\n" if output and not output.endswith("\n") else "") + result.stderr
    return output, result.returncode


def _draw(stdscr, commands, variables, selected, output_lines, status):
    stdscr.erase()
    h, w = stdscr.getmaxyx()

    # title = "Shell demo — up/down navigate · Enter run · q quit"
    # stdscr.addnstr(0, 0, title, w - 1, curses.A_BOLD)

    item = commands[selected]
    desc = f"  {item.description}"
    active = f"  $ {render(item.command, variables)}"
    stdscr.addnstr(2, 0, desc.ljust(w - 1), w - 1, curses.A_BOLD)
    stdscr.addnstr(3, 0, active.ljust(w - 1), w - 1, curses.A_REVERSE)

    sep_row = 5
    if sep_row < h - 1:
        stdscr.addnstr(sep_row, 0, "-" * (w - 1), w - 1)
        stdscr.addnstr(sep_row + 1, 0, status.ljust(w - 1), w - 1, curses.A_DIM)

        out_start = sep_row + 3
        max_out = h - out_start - 1
        if max_out > 0:
            for i, line in enumerate(output_lines[-max_out:]):
                stdscr.addnstr(out_start + i, 0, line, w - 1)

    stdscr.refresh()


def interactive(stdscr, commands: list[Command], variables: dict[str, str]) -> None:
    curses.curs_set(0)
    stdscr.keypad(True)

    selected = 0
    output_lines: list[str] = []
    status = "Ready."

    while True:
        _draw(stdscr, commands, variables, selected, output_lines, status)
        key = stdscr.getch()

        if key in (curses.KEY_UP, ord("k")):
            selected = (selected - 1) % len(commands)
        elif key in (curses.KEY_DOWN, ord("j")):
            selected = (selected + 1) % len(commands)
        elif key in (curses.KEY_ENTER, 10, 13):
            item = commands[selected]
            cmd = render(item.command, variables)
            status = f"Running: {cmd}"
            _draw(stdscr, commands, variables, selected, output_lines, status)
            output, rc = run(cmd)
            output_lines = [f"$ {cmd}"] + output.splitlines()
            if item.post is not None:
                try:
                    extracted = item.post(output, variables)
                except Exception as exc:
                    extracted = f"<post error: {exc}>"
                if extracted:
                    output_lines += ["", f"extracted: {extracted}"]
            status = f"Exit {rc}."
        elif key in (ord("q"), 27):
            break


if __name__ == "__main__":
    variables = {
        "NAME": "kal",
        "CONTAINER": "f5-toda-kal",
        "NAMESPACE": "kal-ns",
        "LEVEL": "NOTICE",
    }

    commands = [
        Command(
            description="List current log levels across all namespaces",
            command="kubectl f5ops ll list -A",
            # post=lambda out: next(
            #     (
            #         f"{parts[1]}/{parts[2]} level = {parts[3]}"
            #         for line in out.splitlines()
            #         if (parts := line.split()) and len(parts) >= 5 and parts[2] == "f5-toda-kal"
            #     ),
            #     None,
            # ),
        ),
        Command(
            description=f"Set log level of $CONTAINER to $LEVEL",
            command="kubectl f5ops ll set $NAME $CONTAINER $LEVEL -n $NAMESPACE",
        ),
        Command(
            description="Re-list log levels to verify the change",
            command="kubectl f5ops ll list -A",
            # post=lambda out: next(
            #     (
            #         f"{parts[1]}/{parts[2]} level = {parts[3]}"
            #         for line in out.splitlines()
            #         if (parts := line.split()) and len(parts) >= 5 and parts[2] == "f5-toda-kal"
            #     ),
            #     None,
            # ),
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
