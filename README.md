<p align="center">
  <strong>Task Pilot</strong><br>
  Terminal UI task manager for Claude Code sessions
</p>

<p align="center">
  <a href="./README.md">English</a> |
  <a href="./README.zh-CN.md">中文</a> |
  <a href="./README.ja.md">日本語</a>
</p>

---

## What is Task Pilot?

Task Pilot is a terminal dashboard that tracks your Claude Code sessions, surfaces action items that need your attention, and lets you resume sessions — acting as a dispatcher panel for multi-session workflows.

**The core idea:** You are the CPU (decision-maker), Claude Code is I/O (code executor). When you juggle multiple sessions, you lose context. Task Pilot solves this by giving you a single pane of glass.

## Features

- **Real-time tracking** — Claude Code hooks automatically capture session events (start, heartbeat, stop, end)
- **Session scanner** — Discovers existing sessions from `~/.claude/` on startup
- **Three-section dashboard** — Tasks grouped by: Action Required / Working / Done
- **Detail view** — Summary, action steps checklist, timeline for each task
- **Session resume** — Press `c` to resume any session in a new terminal
- **Search** — Press `/` to filter tasks by title
- **Auto-refresh** — Dashboard updates every 5 seconds
- **Responsive** — Adapts to terminal width

## Quick Start

```bash
# Install with uv
uv pip install -e .

# Install Claude Code hooks (one-time setup)
task-pilot install-hooks

# Launch the dashboard
task-pilot ui
```

## Architecture

```
SQLite DB  <──  Hooks (real-time)  <──  Claude Code sessions
    |       <──  Scanner (backfill) <──  ~/.claude/ files
    v
  Textual TUI ── List View ── Detail View
```

| Layer | Description |
|-------|-------------|
| `models.py` | Dataclasses: Task, Session, ActionItem, TimelineEvent |
| `db.py` | SQLite CRUD with schema auto-migration |
| `hooks.py` | Claude Code hook installer + event handlers |
| `scanner.py` | Reads `~/.claude/` to discover sessions |
| `summarizer.py` | Transcript parsing + summary generation |
| `cli.py` | Click CLI entry point |
| `app.py` | Textual app shell |
| `screens/` | List screen + Detail screen |
| `widgets/` | HeaderBar, TaskRow, ActionSteps, Timeline |

## Keybindings

| Key | Action |
|-----|--------|
| `Enter` | Open task detail |
| `Esc` | Go back / close search |
| `c` | Resume session |
| `d` | Mark task done |
| `r` | Refresh |
| `/` | Search |
| `n` | New task |
| `q` | Quit |

## Development

```bash
# Setup
uv venv && uv pip install -e ".[dev]"

# Run tests (102 tests)
uv run pytest tests/ -v

# Run the app
uv run task-pilot ui
```

## Tech Stack

- Python 3.11+
- [Textual](https://textual.textualize.io/) — TUI framework
- [Rich](https://rich.readthedocs.io/) — Terminal rendering
- [Click](https://click.palletsprojects.com/) — CLI
- SQLite3 — Local storage
