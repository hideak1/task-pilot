<p align="center">
  <strong>Task Pilot</strong><br>
  Terminal dashboard for orchestrating multiple Claude Code sessions
</p>

<p align="center">
  <a href="./README.md">English</a> |
  <a href="./README.zh-CN.md">中文</a> |
  <a href="./README.ja.md">日本語</a>
</p>

---

## What is Task Pilot?

Task Pilot is a terminal control panel for running and switching between multiple Claude Code sessions without ever leaving your terminal. It is built on top of **tmux**: a single tmux session named `task-pilot` hosts a left pane (pilot's Textual UI) and a right pane (the currently visible Claude Code session). Every other Claude Code session you launch from pilot lives in a hidden `_bg_<uuid>` window, with its process still running normally.

When you pick a different session in the left panel, pilot uses a **two-step swap-pane protocol** to return the currently visible session's pane back to its home `_bg_*` window, then swap the selected session's pane into the right. No session is killed, disconnected, or restarted during the switch.

**Scope (E1):** pilot manages only the sessions *you create from within pilot*. Sessions launched in other terminals are intentionally out of scope.

**Why a rewrite?** The previous v0.1 design relied on Claude Code hooks plus a scanner and an AI summarizer. That path burned tokens in an inner loop and still required you to switch terminals to actually interact with Claude. The tmux model eliminates both problems: zero API calls in the hot path, and the right pane is a real Claude Code TUI you type into directly.

## Features

- **Tmux-based orchestration** — no hooks, no API calls, zero token cost
- **Real-time refresh** — every 2 seconds, reading directly from `~/.claude/projects/*.jsonl`
- **Live token counting** — tail-reads each transcript and sums `input_tokens + output_tokens` from assistant messages
- **Status detection** — `initializing` / `working` / `idle` / `unknown`, derived purely from local transcript activity
- **Per-session context** — working directory (with `~` abbreviation) and git branch shown on each row
- **Two-step swap-pane switching** — instant visual swap, no process restart
- **Mouse + keyboard navigation** — click rows, scroll inside Claude, or use vim-style keys
- **Command bar (`:q`)** — vim-style quit that tears down every managed session cleanly
- **Crash-resilient** — pilot runs under a watchdog wrapper; reconciles with tmux on startup to adopt orphan windows

## Quick Start

```bash
uv venv && uv pip install -e .
task-pilot ui      # bootstrap or attach to tmux session
```

Running `task-pilot ui` is idempotent:
- If the `task-pilot` tmux session does not exist, it is bootstrapped with the two-pane layout and pilot is launched in the left pane.
- If it already exists, `task-pilot ui` attaches to it.
- If you run it from inside a *different* tmux session, pilot prints actionable guidance instead of silently misbehaving.

## Keybindings

| Key               | Action                                                                 |
|-------------------|------------------------------------------------------------------------|
| `j` / `k` / `↑` / `↓` | Move selection in the left panel                                   |
| `Enter`           | Switch to the selected session (two-step swap-pane) and focus right    |
| `Tab`             | Toggle focus between the left panel and the right pane                 |
| `n`               | New session — opens a dialog with recent directories + Tab completion  |
| `x`               | Close the selected session (with confirmation)                         |
| `r`               | Force refresh (also re-resolves git branch and transcript path)        |
| `/`               | Search / filter rows by title or cwd substring                         |
| `:`               | Open the command bar                                                   |
| `:q` + `Enter`    | Quit pilot and kill every managed Claude Code process                  |

There is intentionally no plain `q` quit key — `:q` is deliberately hard to mis-type, so no confirmation dialog is needed.

## Architecture

```
┌─── tmux session: task-pilot ──────────────────────┐
│                                                    │
│  Window: main                                      │
│  ┌──────────────────┬──────────────────────────┐  │
│  │                  │                          │  │
│  │  pilot (Textual) │  Claude Code session     │  │
│  │  left list       │  (currently selected)    │  │
│  │                  │                          │  │
│  └──────────────────┴──────────────────────────┘  │
│                                                    │
│  Window: _bg_<uuid1>  →  session A's pane (hidden)│
│  Window: _bg_<uuid2>  →  session B's pane (hidden)│
│  Window: _bg_<uuid3>  →  session C's pane (hidden)│
│                                                    │
└────────────────────────────────────────────────────┘
```

- One dedicated tmux session: `task-pilot`.
- Window `main` always has two panes: pilot on the left, the currently visible Claude Code session on the right.
- Every other Claude Code session lives in its own `_bg_<uuid>` window. These windows are never displayed, but their Claude Code processes keep running.
- On switching sessions, pilot runs a two-step `swap-pane`: step 1 returns the current pane to its home `_bg_*` window; step 2 brings the target pane into `main.1`.
- On startup, pilot reconciles state: DB rows without a matching tmux window are dropped, and `_bg_*` windows without a DB row are adopted.

## Platform Support

| Platform                                 | Status        |
|------------------------------------------|---------------|
| macOS (iTerm2, Terminal.app, Kitty, …)   | Supported     |
| Linux (any terminal with tmux)           | Supported     |
| WSL2 on Windows                          | Supported     |
| Remote Ubuntu via SSH                    | Recommended   |
| VS Code Remote-SSH + integrated terminal | Supported     |
| Native Windows (PowerShell, CMD, Git Bash) | Not supported — use WSL2 |

## Requirements

- Python 3.11+
- tmux 3.0+
- Claude Code CLI (`claude`) in `PATH`
- `psutil` Python package
- A UTF-8 terminal with 256 colors (a Nerd Font is recommended for row separators and status icons)

## Development

```bash
uv venv && uv pip install -e ".[dev]"
.venv/bin/pytest tests/ -v   # 125+ tests
```

## Tech Stack

- [Python 3.11+](https://www.python.org/)
- [Textual](https://textual.textualize.io/) — TUI framework for the left panel
- SQLite — persistent session state (`sessions` and `pilot_state` tables)
- [tmux](https://github.com/tmux/tmux) 3.0+ — session orchestration and pane swapping
- [psutil](https://github.com/giampaolo/psutil) — cross-platform process inspection to locate Claude Code transcripts
- [Click](https://click.palletsprojects.com/) — CLI entry point
