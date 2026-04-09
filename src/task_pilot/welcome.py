"""Welcome banner for the right pane before any session is created.

Run as `python -m task_pilot.welcome`. Blocks forever so the tmux pane
stays alive until the user creates a session (which swaps this pane out).
"""

from __future__ import annotations

import time

from rich.align import Align
from rich.console import Console, Group
from rich.panel import Panel
from rich.text import Text


LOGO = r"""
 _____         _    ___ _ _     _
|_   _|_ _ ___| |__| _ (_) |___| |_
  | |/ _` (_-< / /|  _/ | / _ \  _|
  |_|\__,_/__/_\_\|_| |_|_\___/\__|
"""


def render() -> Panel:
    logo = Text(LOGO, style="bold #74c0fc")
    tagline = Text(
        "Terminal dashboard for orchestrating Claude Code sessions",
        style="italic #8b8fa3",
        justify="center",
    )

    def hint(key: str, text: str) -> Text:
        line = Text("  ")
        line.append("▸ ", style="#74c0fc")
        line.append(key.ljust(10), style="bold #ffd43b")
        line.append(text, style="#e2e4e9")
        return line

    hints = Group(
        Text(),
        Text("  Quick start", style="bold #e2e4e9"),
        Text("  " + "─" * 40, style="#555869"),
        Text(),
        hint("n",        "Create a new Claude Code session"),
        hint("j / k",    "Move selection in the left panel"),
        hint("Enter",    "Switch to the selected session"),
        hint("/",        "Search sessions by title or cwd"),
        hint("x",        "Close the selected session"),
        hint("r",        "Refresh now (otherwise every 2s)"),
        hint(":q",       "Quit Task Pilot"),
        Text(),
        Text(
            "  This pane will be replaced by your session once you create one.",
            style="italic #555869",
        ),
    )

    body = Group(
        Text(),
        Align.center(logo),
        Align.center(tagline),
        hints,
        Text(),
    )

    return Panel(
        body,
        border_style="#181b22",
        padding=(1, 2),
        title="[#74c0fc]welcome[/]",
        title_align="left",
    )


def main() -> None:
    console = Console()
    console.print(render())
    # Sleep forever; pilot will swap this pane out when the user creates
    # the first session. Ctrl+C cleanly exits if the user wants to poke around.
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
