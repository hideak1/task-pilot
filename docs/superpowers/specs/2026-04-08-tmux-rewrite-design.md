# Task Pilot — Tmux-based UI Rewrite Design

**Date:** 2026-04-08
**Status:** Design
**Author:** Brainstorm session

## Goals

Rewrite Task Pilot's UI layer around a tmux-based orchestration model where each
Claude Code session runs in a tmux window and pilot acts as a control panel that
swaps which session is currently visible. This replaces the previous design of
hooks + scanner + detail screen with a simpler, safer, and more useful model.

### Success criteria

1. Launching `task-pilot ui` brings up a two-pane tmux layout: pilot on the left,
   a Claude Code session on the right.
2. User can launch new Claude Code sessions from within pilot, each in its own
   working directory, each running independently and persistently.
3. Switching the selected session in pilot's left panel instantly swaps which
   Claude Code session appears in the right pane. No session is killed or
   disconnected during a switch.
4. Left panel shows, for each live session: title, cwd, git branch, elapsed time,
   cumulative token count, and run state (working / idle).
5. No Claude Code hooks are required. No `~/.claude/settings.json` modification.
   Zero risk of token-burn loops.
6. Works on macOS, Linux, WSL2, and remote Ubuntu via SSH / VS Code Remote-SSH.

### Non-goals

- Managing Claude Code sessions launched from other terminals (E1 scope only).
- History / archive view of closed sessions.
- Token cost attribution across multiple days.
- Windows native support (without WSL2).

## Background

The v0.1 design used Claude Code hooks to track sessions in real time and a
scanner to backfill historical data. Two problems surfaced:

1. **Token drain.** The summarizer called `claude --print`, which spawned new
   Claude Code sessions, which triggered `SessionStart` hooks, which scanned
   transcripts, which called `claude --print` again. This burned the user's
   token budget on an inner loop.
2. **Weak value.** The detail screen showed a rendered view of the transcript
   but the user could not interact with Claude Code from inside pilot. Users
   still had to switch terminals to actually do work.

This rewrite eliminates both problems: no API calls at all in the hot path,
and the right panel is a real Claude Code TUI that the user can interact with
directly.

## Architecture

### Tmux session layout

```
┌─── tmux session: task-pilot ────────────────────┐
│                                                  │
│  Window: main                                    │
│  ┌──────────────────┬────────────────────────┐  │
│  │                  │                        │  │
│  │  pilot (Textual) │  Claude Code session   │  │
│  │  left list       │  (currently selected)  │  │
│  │                  │                        │  │
│  └──────────────────┴────────────────────────┘  │
│                                                  │
│  Window: _bg_<uuid1>  →  session A's pane       │
│  Window: _bg_<uuid2>  →  session B's pane       │
│  Window: _bg_<uuid3>  →  session C's pane       │
│                                                  │
└──────────────────────────────────────────────────┘
```

- One dedicated tmux session named `task-pilot`.
- Window `main` always has two panes: pilot on the left, currently-selected
  Claude Code session on the right.
- Every other Claude Code session lives as a single-pane window named
  `_bg_<session_uuid>`. These windows are never displayed to the user, but the
  Claude Code process in each of them keeps running normally.

### Launcher (`task-pilot ui`)

```
if in tmux AND tmux session is "task-pilot":
    run Textual app directly (developer mode)
elif not in tmux:
    if tmux has-session -t task-pilot:
        tmux attach -t task-pilot          # reattach existing session
    else:
        tmux new-session -d -s task-pilot  # first time: create
        tmux split-window -h -t task-pilot:main
        tmux send-keys -t task-pilot:main.0 "python -m task_pilot.textual_app" Enter
        tmux set -t task-pilot mouse on
        tmux attach -t task-pilot
elif in tmux but not task-pilot:
    exec inside outer tmux with a nested tmux?  # Rejected: too messy.
    print error and exit.
```

This is idempotent: re-running `task-pilot ui` always returns the user to the
correct state.

### Switching sessions (swap-pane mechanism)

tmux does not allow "hiding" a pane, but a pane can be moved between windows
while keeping its child process running. To display session B when A is currently
visible:

```
tmux swap-pane -s task-pilot:main.1 -t task-pilot:_bg_<B>.0
```

After this call:
- The pane containing session A's Claude Code moves into window `_bg_<A>`.
- The pane containing session B's Claude Code moves into `main.1` (right side).
- Neither Claude Code process is killed or restarted.
- User sees session B in the right pane.

### Reconciliation (startup)

pilot must be robust to crashes and inconsistent state between DB and tmux:

```
on pilot startup:
    tmux_windows = tmux.list_windows("task-pilot")  # set of _bg_* names
    db_sessions = db.list_sessions()

    # DB has a session but tmux doesn't → it died, remove from DB
    for s in db_sessions:
        if s.tmux_window not in tmux_windows:
            db.delete_session(s.id)

    # tmux has a window but DB doesn't → adopt it (pilot was restarted)
    for w in tmux_windows:
        if w not in db_sessions:
            db.insert_adopted_session(w)
```

## Data Model

### SQLite schema

```sql
CREATE TABLE sessions (
    id              TEXT PRIMARY KEY,     -- pilot UUID
    tmux_window     TEXT NOT NULL UNIQUE, -- "_bg_<uuid>"
    cwd             TEXT NOT NULL,
    git_branch      TEXT,                 -- nullable: not a git repo
    started_at      REAL NOT NULL,        -- Unix timestamp
    title           TEXT                  -- extracted / AI-generated
);
```

Previous tables (`tasks`, `action_items`, `timeline_events`, old `sessions`) are
dropped without migration. No user data is lost because the v0.1 DB only
contained test data.

### Python dataclass

```python
@dataclass
class Session:
    # Persistent fields
    id: str
    tmux_window: str
    cwd: str
    git_branch: str | None
    started_at: float
    title: str | None

    # Runtime fields (not persisted; computed on each refresh)
    is_alive: bool = True
    last_activity: float = 0.0
    token_count: int = 0
    claude_session_id: str | None = None
```

### Finding a Claude Code transcript for a session

When pilot creates a tmux window running `claude`, Claude Code assigns itself
a new session UUID which pilot does not know in advance. To find the transcript:

**Primary method (by PID):**
1. `tmux list-panes -t :_bg_<uuid> -F '#{pane_pid}'` → shell PID
2. Walk `/proc/<pid>/task/*/children` or use `ps` to find the `claude` child PID
3. Search `~/.claude/sessions/*.json` for an entry whose `pid` matches
4. That file's `sessionId` field gives the Claude session UUID
5. Transcript path: `~/.claude/projects/<slug>/<sessionId>.jsonl`
   where `<slug>` is derived from cwd

**Fallback method (by cwd and time):**
1. Compute slug from cwd: `/Users/foo/bar` → `-Users-foo-bar`
2. List `.jsonl` files in `~/.claude/projects/<slug>/`
3. Pick the one whose mtime is after pilot's `started_at` and closest to it

The result is cached in memory; pilot only re-resolves if the cached path
becomes invalid.

### Token counting

Read the last N lines of the transcript `.jsonl` file (tail-read to avoid
re-parsing multi-megabyte transcripts). For each `assistant` message, sum
`message.usage.input_tokens + message.usage.output_tokens`. Display in the
left panel as `45k tok`.

Refresh interval: every 2 seconds. Only re-read files whose mtime changed.

## UI Layout

### Left panel

```
┌────────────────────────────────────┐
│ Task Pilot        3 running  1 idle│   header
├────────────────────────────────────┤
│ ▸ Build REST API             [●]  │   selected (blue left border)
│   ~/proj/my-api · main             │
│   2h 15m · 45k tok                 │
├────────────────────────────────────┤
│   Fix login bug              [●]  │
│   ~/proj/webapp · fix/auth         │
│   23m · 12k tok                    │
├────────────────────────────────────┤
│   Debug memory leak          [◐]  │   idle
│   ~/proj/core                      │   no git branch
│   1h 3m · 78k tok                  │
├────────────────────────────────────┤
│                                    │
│ n:new  x:close  /:search  :q:quit  │   footer
└────────────────────────────────────┘
```

Each row is 3 lines:
- Line 1: title + status icon (`●` = working, `◐` = idle)
- Line 2: cwd (with `~` abbreviation) + optional `· <branch>`
- Line 3: elapsed time · token count

### Title source

- **Freshly created session:** placeholder `"New session"` with the cwd basename.
- **After first user message:** extract the first user message from the transcript.
  Clean XML tags, strip to first line, truncate to 60 chars.
- **Background AI upgrade (optional):** every 30 seconds, for sessions whose
  title is still a fallback, call `codex exec --sandbox read-only` to generate
  a better one. Failures silently fall back to the heuristic title. This is the
  only external process pilot spawns.

### Status detection

- **Working:** transcript has a new message within the last 30 seconds.
- **Idle:** no new messages in the last 30 seconds (Claude is waiting for input,
  or the user stepped away).
- Sessions whose tmux window disappears are deleted from the list on the next
  refresh cycle. There is no "closed" state.

### Elapsed time

Displayed as elapsed since `started_at`, never as "just now":
- `< 60s` → `45s`
- `< 60m` → `23m`
- `≥ 60m` → `2h 15m`

This is the `now - started_at` computation, done fresh on each render. It fixes
the v0.1 bug where all sessions showed "刚刚" because `updated_at` was being
written by heartbeats.

## Interaction

### Keybindings

| Key                 | Action                                           |
|---------------------|--------------------------------------------------|
| `↑` / `↓` / `j` / `k` | Move selection                                  |
| `Enter` / double-click | Shift focus to the right pane (Claude Code)    |
| `Tab`               | Toggle focus between left and right panes        |
| `n`                 | Launch new session (open directory picker)       |
| `x`                 | Close selected session (confirmation dialog)     |
| `/`                 | Search (filter by title or cwd)                  |
| `r`                 | Manual refresh                                   |
| `:` → `q` → `Enter` | Quit (vim-style command mode, full kill)         |

Mouse:
- Click a row → select it
- Double-click a row → shift focus to right pane
- Click the right pane → focus follows (tmux mouse mode)
- Scroll in the right pane → Claude Code scroll (tmux passes through)

### New session dialog

```
┌─ New Session ──────────────────────┐
│                                    │
│  Recent directories:               │
│  ▸ ~/project/task_management       │
│    ~/project/celpip                │
│    ~/project/my-api                │
│    ~/project/webapp                │
│                                    │
│  Or type a path:                   │
│  [_________________________]       │
│                                    │
│  Enter: create   Esc: cancel       │
└────────────────────────────────────┘
```

- Recent directories are extracted from `~/.claude/history.jsonl` (deduplicated,
  sorted by most recent, top 10).
- Arrow keys select from the list; typing in the input overrides.
- `Tab` in the input field triggers path completion:
  - One match → complete the full path
  - Multiple matches → complete to longest common prefix
  - Second `Tab` → show candidates (bash-style)
- `Enter` launches:
  ```
  uuid = new_uuid()
  tmux new-window -d -n _bg_<uuid> -c <cwd> 'claude'
  db.insert(...)
  tmux swap-pane -s :main.1 -t :_bg_<uuid>.0  # show it immediately
  ```
- The session starts as a blank Claude Code (no initial prompt).

### Close confirmation

```
Close "Build REST API"? This kills the Claude Code process.
[y] Yes   [n] No
```

On `y`: `tmux kill-window -t :_bg_<uuid>`, then delete from DB.

### Quit (`:q` + Enter)

Full shutdown of everything:
1. For each session in DB: `tmux kill-window`
2. `tmux kill-session -t task-pilot`
3. Exit the Textual app

`:q` is a command-mode sequence modeled after vim: `:` opens a command input,
`q` is the command, `Enter` executes. This is hard enough to mis-type that
no confirmation dialog is needed.

## Platform Support

| Platform                                 | Status       |
|-------------------------------------------|--------------|
| macOS (iTerm2, Terminal.app, Kitty, etc.) | ✅ Supported |
| Linux (any terminal with tmux)            | ✅ Supported |
| WSL2 on Windows                           | ✅ Supported |
| Remote Ubuntu via SSH from any OS         | ✅ Recommended |
| VS Code Remote-SSH + integrated terminal  | ✅ Supported |
| Windows native (PowerShell, CMD)          | ❌ Use WSL2  |
| Git Bash on Windows                       | ❌ Use WSL2  |

Minimum requirements:
- Python 3.11+
- tmux 3.0+
- Claude Code CLI installed (`claude` in PATH)
- UTF-8 terminal with 256 colors

VS Code users should add this to settings.json if they find `:q` doesn't reach
the terminal:
```json
"terminal.integrated.allowChords": true
```

## Code Changes

### Keep
- `src/task_pilot/config.py`
- `src/task_pilot/summarizer.py` (title extraction; codex fallback kept)
- `src/task_pilot/db.py` (schema changes, CRUD preserved)

### Rewrite
- `src/task_pilot/models.py` — `Task` → `Session` with new fields
- `src/task_pilot/app.py` — orchestrates tmux launch instead of running Textual directly
- `src/task_pilot/cli.py` — drop `install-hooks`, `scan`, `hook` subcommands

### Delete
- `src/task_pilot/hooks.py`
- `src/task_pilot/scanner.py`
- `src/task_pilot/screens/detail_screen.py`
- `src/task_pilot/widgets/action_steps.py`
- `src/task_pilot/widgets/timeline.py`
- `src/task_pilot/widgets/header_bar.py` (likely replaced)

### New
- `src/task_pilot/tmux.py` — thin wrapper around tmux CLI commands
- `src/task_pilot/session_tracker.py` — session lifecycle and reconciliation
- `src/task_pilot/launcher.py` — tmux launch-or-attach logic
- `src/task_pilot/transcript_reader.py` — tail-reads `.jsonl` for tokens and activity
- `src/task_pilot/widgets/session_row.py` — 3-line row widget
- `src/task_pilot/widgets/new_session_dialog.py` — directory picker with Tab completion
- `src/task_pilot/screens/list_screen.py` — rewritten as single-panel list
- `src/task_pilot/textual_app.py` — the Textual app that runs inside the left pane

### Test changes

Delete:
- `tests/test_hooks.py`
- `tests/test_scanner.py`
- `tests/test_integration_cli.py`

Rewrite / heavily modify:
- `tests/test_models.py`
- `tests/test_db.py`
- `tests/test_cli.py`
- `tests/test_tui.py`
- `tests/test_e2e.py`

New:
- `tests/test_tmux.py`
- `tests/test_session_tracker.py`
- `tests/test_launcher.py`
- `tests/test_transcript_reader.py`
- `tests/test_new_session_dialog.py`
- `tests/test_session_row.py`

All tests must pass before each phase is considered complete.

## Development Phases

Each phase is independently runnable and testable.

### Phase 1 — Tmux control layer and launcher

Files: `tmux.py`, `launcher.py`, `test_tmux.py`, `test_launcher.py`

Goal: `task-pilot ui` creates a tmux session `task-pilot` with a main window
split horizontally, left pane running a placeholder Python script that prints
"pilot placeholder". Re-running attaches to the existing session. `:q` equivalent
(for now, just a CLI `task-pilot kill`) cleanly tears everything down.

No UI logic, no DB. Verifies tmux orchestration in isolation.

### Phase 2 — Data layer and session tracker

Files: `models.py`, `db.py`, `session_tracker.py`, `transcript_reader.py`,
`test_models.py`, `test_db.py`, `test_session_tracker.py`, `test_transcript_reader.py`

Goal: Create, kill, list, and reconcile sessions in DB. Read token counts from
transcript. Pure Python, no UI.

### Phase 3 — Left panel TUI (static)

Files: `textual_app.py`, `screens/list_screen.py`, `widgets/session_row.py`,
`test_tui.py`

Goal: Textual app that loads seed data from DB and renders the 3-line row
layout correctly. Selection with arrow keys. No live refresh yet, no
interaction with tmux.

### Phase 4 — Live data

Goal: Refresh the list every 2 seconds. Read transcripts for token/activity.
Detect dead sessions and remove them. Cache git branch. Title extraction.

### Phase 5 — Interaction

Files: `widgets/new_session_dialog.py`

Goal:
- `n` opens directory picker with Tab completion
- `Enter` launches new Claude Code session in tmux
- `x` closes selected session with confirmation
- Selecting a session calls `tmux swap-pane`
- `:q` + Enter command mode quits everything
- Mouse click on rows

### Phase 6 — Polish

Goal:
- Tmux mouse-mode coexistence with Textual
- Focus cycling between panes
- Error handling: tmux binary missing, Claude Code not installed, Claude session
  crash detection, tmux session corruption
- README rewrite

## Risks and Mitigations

| Risk                                                    | Mitigation                                               |
|---------------------------------------------------------|----------------------------------------------------------|
| tmux `swap-pane` races if the target pane is gone       | Check window exists before swapping; recover gracefully  |
| Claude Code writes `~/.claude/sessions/*.json` with delay, causing transcript resolution to fail on first refresh | Retry with exponential backoff for 5 seconds after session creation |
| User's tmux config overrides our key bindings           | Pilot operates from within its Textual app; tmux prefix keys do not conflict |
| VS Code terminal intercepts `Ctrl+` combos              | `:q` command mode avoids modifiers entirely              |
| Nested TUI rendering (Claude in tmux in VS Code term)   | Tested combination; widely used in practice              |
| `codex exec` for AI titles being slow or absent         | Already optional; falls back silently                    |
| Long transcripts slow down token counting               | Tail-read only; cache last-read offset                   |
| Git branch lookup is slow on network filesystems        | Cache per session; only refresh on explicit `r`          |

## Open Questions

None. All design decisions resolved during the brainstorming session.

## References

- Previous design (v0.1): `docs/superpowers/plans/2026-03-24-task-pilot.md`
  (deleted after v0.1 shipped; referenced from commit history)
- Similar tools studied during brainstorm:
  - [CCManager](https://github.com/kbwo/ccmanager) — PTY-based, no tmux
  - [Recon](https://github.com/gavraz/recon) — Rust TUI, reads ~/.claude/
  - [claude-session-driver](https://github.com/obra/claude-session-driver) —
    controller/worker pattern over tmux
