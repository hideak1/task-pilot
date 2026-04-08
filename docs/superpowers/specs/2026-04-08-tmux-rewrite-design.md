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

```python
def main():
    # Pre-flight checks
    if not shutil.which("tmux"):
        die("tmux is not installed. Install via your package manager.")
    if not shutil.which("claude"):
        die("claude CLI not found in PATH. Install Claude Code first.")

    in_tmux = bool(os.environ.get("TMUX"))
    current_session = (
        subprocess.check_output(["tmux", "display-message", "-p", "#S"]).strip()
        if in_tmux else None
    )

    if in_tmux and current_session == "task-pilot":
        # Developer mode: we're already inside our session, just run the app
        run_textual_app()
        return

    if in_tmux and current_session != "task-pilot":
        # User is in some other tmux session
        if tmux_has_session("task-pilot"):
            print("You are inside tmux session", current_session)
            print("Run:    tmux switch-client -t task-pilot")
            print("Or detach (Ctrl-b d) then re-run task-pilot ui")
        else:
            print("You are inside tmux session", current_session)
            print("Detach first (Ctrl-b d), then run task-pilot ui")
        sys.exit(1)

    # Not in tmux at all
    if tmux_has_session("task-pilot"):
        os.execvp("tmux", ["tmux", "attach", "-t", "task-pilot"])

    # First-time bootstrap
    bootstrap_tmux_session()
    os.execvp("tmux", ["tmux", "attach", "-t", "task-pilot"])


def bootstrap_tmux_session():
    tmux("new-session", "-d", "-s", "task-pilot", "-n", "main",
         "-x", "200", "-y", "50")          # detached so we can configure it
    tmux("set", "-t", "task-pilot", "mouse", "on")
    tmux("set", "-t", "task-pilot", "-g", "status", "off")  # hide tmux status bar
    tmux("split-window", "-h", "-t", "task-pilot:main", "-l", "70%")
    # Left pane runs pilot under a wrapper that restarts it on crash
    tmux("send-keys", "-t", "task-pilot:main.0",
         "exec python -m task_pilot.textual_app --watchdog", "Enter")
```

`--watchdog` makes the Textual entry point trap exceptions and re-launch
itself; if it crashes 3+ times in 60s it stays dead and prints a message
in the left pane. The right pane (`main.1`) starts as a plain shell with a
prompt — see Phase 1 for the placeholder text.

This is idempotent: re-running `task-pilot ui` either attaches to the
existing session, runs the Textual app inside it, or prints actionable
guidance for unusual nested-tmux situations. There is no path that
silently fails.

### Switching sessions (two-step swap-pane protocol)

tmux does not allow "hiding" a pane, but a pane can be moved between windows
while keeping its child process running. A naive single swap breaks the
invariant that session X's Claude process lives in `_bg_<X>` — after one
switch, DB records would point to the wrong windows. The fix is a **two-step
swap protocol**: before showing a new session, first return the currently
visible session's pane back to its home `_bg_<current>` window.

```python
def switch_to(target_id: str) -> None:
    current_id = db.get_current_session_id()  # nullable
    if current_id:
        # Step 1: return current's pane from main.1 back to its home window
        tmux("swap-pane", "-s", "task-pilot:main.1",
                          "-t", f"task-pilot:_bg_{current_id}.0")
    # Step 2: bring target's pane from its home window into main.1
    tmux("swap-pane", "-s", "task-pilot:main.1",
                      "-t", f"task-pilot:_bg_{target_id}.0")
    db.set_current_session_id(target_id)
```

After this sequence:
- Each session's Claude Code pane lives in `_bg_<its_uuid>` whenever it is NOT
  the currently-visible session.
- The currently-visible session's pane lives in `main.1`.
- `db.current_session_id` tracks which session is currently in `main.1`.
- Neither Claude Code process is killed or restarted during the swap.

The invariant `session.tmux_window == "_bg_<session.id>"` is preserved as the
*home* of each session. The only exception at any instant is the one session
whose id equals `current_session_id` — its pane is temporarily in `main.1`.

**Bootstrap case:** on first session creation, `current_session_id` is `None`
and `main.1` holds a placeholder shell. The switch code's step 1 is skipped
(nothing to return home), and step 2 swaps the placeholder out and the new
session in. The placeholder pane ends up in `_bg_<new>` as an inert extra pane,
which is harmless — step 2 is actually a single-pane swap; tmux creates the
pane in the target window if needed. See Phase 1 tests for the exact sequence.

### Reconciliation (startup)

pilot must be robust to crashes and inconsistent state between DB and tmux:

```python
def reconcile():
    # 0. Ensure main window is alive (pilot was killed mid-recreation, etc.)
    if not tmux.window_exists("task-pilot:main"):
        tmux.recreate_main_window()  # new window + split + restart pilot
        db.clear_current_session()   # nothing visible

    tmux_windows = tmux.list_windows("task-pilot")  # all _bg_* names
    db_sessions = db.list_sessions()

    # 1. DB has a session but tmux window is gone → process died, drop record
    for s in db_sessions:
        if s.tmux_window not in tmux_windows:
            db.delete_session(s.id)
            if db.get_current_session_id() == s.id:
                db.clear_current_session()

    # 2. tmux has a window but DB doesn't → adopt the orphan
    db_window_names = {s.tmux_window for s in db_sessions}
    for w in tmux_windows:
        if w in db_window_names:
            continue
        # Recover what we can from tmux itself
        cwd = tmux.display("#{pane_current_path}", target=f"{w}.0")
        # window_activity is in seconds since epoch (tmux 3.0+)
        started_at = float(tmux.display("#{window_activity}", target=w))
        adopted_uuid = w[len("_bg_"):]  # the uuid is in the window name
        db.insert_session(
            id=adopted_uuid,
            tmux_window=w,
            cwd=cwd or "/",
            git_branch=None,
            started_at=started_at,
            title=None,  # will be re-extracted from transcript on next refresh
        )
```

The schema must allow `cwd` to fall back to `/` and `started_at` to fall back
to current time if tmux variables are unavailable. `git_branch` and `title`
are nullable and will be filled in by the next refresh tick. The window name
`_bg_<uuid>` carries the session's stable id, so the adopted record has the
same id it had before pilot crashed.

## Data Model

Previous tables (`tasks`, `action_items`, `timeline_events`, old `sessions`)
are dropped without migration. No user data is lost because the v0.1 DB only
contained test data.

### Python dataclasses

Persistent and runtime state are kept in separate dataclasses to avoid the
common footgun of "which fields go through `db.update`?".

```python
@dataclass
class Session:
    """Persistent state — exactly one row in the `sessions` table."""
    id: str
    tmux_window: str
    cwd: str
    git_branch: str | None
    started_at: float
    title: str | None

@dataclass
class SessionState:
    """Runtime state — owned by SessionTracker, never persisted."""
    session_id: str
    is_alive: bool = True
    last_activity: float = 0.0
    token_count: int = 0
    claude_session_id: str | None = None
    transcript_path: Path | None = None
    status: str = "initializing"  # initializing | working | idle | unknown
```

`db.py` only ever reads/writes `Session`. `session_tracker.py` builds a
`{session_id: SessionState}` dict on each refresh and merges it with the
persistent records when the UI needs to render a row. The `current_session_id`
(which session's pane is in `main.1`) is stored in a separate single-row
`pilot_state` table — see schema below.

### SQLite schema (revised)

```sql
CREATE TABLE sessions (
    id              TEXT PRIMARY KEY,     -- pilot UUID
    tmux_window     TEXT NOT NULL UNIQUE, -- "_bg_<uuid>"
    cwd             TEXT NOT NULL DEFAULT '/',
    git_branch      TEXT,
    started_at      REAL NOT NULL,
    title           TEXT
);

CREATE TABLE pilot_state (
    key             TEXT PRIMARY KEY,
    value           TEXT
);
-- Used for: current_session_id, schema_version, etc.
```

`cwd` has a `DEFAULT '/'` so the reconciliation adoption path can insert
records when tmux can't tell us the cwd. `started_at` falls back to
`time.time()` at insert time inside the adoption code.

### Finding a Claude Code transcript for a session

When pilot creates a tmux window running `claude`, Claude Code assigns itself
a new session UUID which pilot does not know in advance. To find the transcript,
use **psutil** for cross-platform process inspection (works on macOS, Linux,
WSL2 — none of which can rely on `/proc` uniformly).

**Primary method (by PID via psutil):**
1. `tmux list-panes -t :_bg_<uuid> -F '#{pane_pid}'` → shell PID
2. `psutil.Process(shell_pid).children(recursive=True)` → list of descendant
   processes; find one whose `name()` is `claude` or whose `cmdline()` starts
   with `claude`
3. Search `~/.claude/sessions/*.json` for an entry whose `pid` matches the
   claude PID
4. That file's `sessionId` field gives the Claude session UUID
5. Transcript path: `~/.claude/projects/<slug>/<sessionId>.jsonl`
   where `<slug>` is derived from cwd: replace `/` with `-`, prefix with `-`

**Fallback method (by cwd and time):**
1. Compute slug from cwd: `/Users/foo/bar` → `-Users-foo-bar`
2. List `.jsonl` files in `~/.claude/projects/<slug>/`
3. Pick the one whose `ctime` is `>= session.started_at - 2s` and closest to
   `started_at`. The 2-second tolerance covers clock skew between pilot and
   Claude Code's file write.

**Race window:** Claude Code may take up to 5 seconds after launch to write
its `~/.claude/sessions/*.json` and create the transcript. During this
window, both methods return `None`. The session row in pilot is shown anyway
with placeholder values: `claude_session_id=None`, `token_count="—"`, status
icon shows `[…]` (initializing). The next refresh tick re-attempts resolution.
After 30 seconds of failed resolution, the row is shown with status `[?]` but
the session is NOT killed — the user might still want to interact with it.

The successful result is cached in memory; pilot only re-resolves if the
cached path no longer exists.

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

- **Initializing** (`[…]`): session was just created, transcript not yet found
- **Working** (`[●]`): transcript has a new message within the last 30 seconds
- **Idle** (`[◐]`): no new messages in the last 30 seconds (Claude is waiting
  for input, or the user stepped away)
- **Unknown** (`[?]`): transcript resolution has been failing for >30s; pane
  is not killed, just flagged
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

| Key                 | Action                                              |
|---------------------|-----------------------------------------------------|
| `↑` / `↓` / `j` / `k` | Move selection                                     |
| `Enter` / double-click | Switch to selected session (swap-pane) and focus right |
| `Tab`               | Toggle focus between left and right panes           |
| `n`                 | Launch new session (open directory picker)          |
| `x`                 | Close selected session (confirmation dialog)        |
| `/`                 | Search (filter rows by title or cwd substring)      |
| `r`                 | Force refresh (also re-resolves git branch + transcript path) |
| `:`                 | Open command bar at the bottom of the left panel    |
| `:` → `q` → `Enter` | Quit (kills tmux session and all Claude Code processes) |

**Refresh semantics:**
- Auto-refresh runs every 2 seconds. It re-reads transcript tails for tokens
  and `last_activity`, and re-checks tmux window liveness. It uses cached
  `git_branch`, cached `transcript_path`, and cached `claude_session_id`.
- Manual `r` does everything auto-refresh does, *plus* re-runs `git -C <cwd>
  rev-parse --abbrev-ref HEAD`, plus retries failed transcript-path resolution
  for sessions that are still in the `initializing` or `unknown` state.

**Search behavior (`/`):**
- Pressing `/` opens a search input at the bottom of the left panel
- As the user types, rows are **filtered** (non-matching rows are hidden)
- Match is case-insensitive substring against `title` and `cwd`
- `Esc` clears the filter and closes the search input
- Selection persists if the selected row is still in the filtered set, otherwise
  selection moves to the first visible row

**Command bar (`:`):**
- Pressing `:` reveals a one-line command bar at the bottom of the left panel:
  ```
  ┌────────────────────────────────────┐
  │ ...rows...                         │
  ├────────────────────────────────────┤
  │ :_                                 │
  └────────────────────────────────────┘
  ```
- Implemented as a Textual `Input` widget with the leading `:` prefix
- Recognized commands (Phase 5):
  - `:q` + Enter → quit (kill tmux session and all Claude Code processes)
  - `:q!` + Enter → same as `:q` (vim-style escape hatch)
  - `Esc` → cancel
- Unknown commands print a one-line error in the command bar (`E: not a command`)
- The command bar is the *only* way to quit pilot. There is no `q` keybinding.

### Mouse behavior

Tmux mouse mode is enabled (`set -g mouse on`) so that the user can click
inside the right pane to give it keyboard focus. To prevent the well-known
trap where scrolling the wheel inside a pane enters tmux's copy-mode and
captures the keyboard, pilot's tmux config disables wheel→copy-mode:

```
unbind-key -T root WheelUpPane
unbind-key -T root WheelDownPane
```

These rebinds are applied at bootstrap time via `tmux set -t task-pilot ...`.
The Claude Code TUI receives wheel events directly and handles them itself
(scrolling its own conversation history). The user never gets stuck in a
copy-mode session they didn't ask for.

In the **left panel**, Textual handles its own click events:
- Click a row → select it
- Double-click a row → switch to that session (swap-pane) and shift focus right
- Click the command bar / search input → focus the input

### Terminal resize

When the terminal is resized, tmux preserves the **percentage split** of
panes by default, so the left/right ratio stays roughly 30/70. To make this
deterministic, the launcher sets:

```
tmux split-window -h -t task-pilot:main -l 70%
```

after which a `client-resized` hook is **not** installed — tmux's default
proportional behavior is sufficient. The Textual app inside the left pane
re-renders on its `on_resize` event to adapt the row width.

The minimum useful left-panel width is **30 columns**. Below that, row content
truncates aggressively but the app does not crash. There is no minimum height.

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
  ```python
  uuid = new_uuid()
  tmux("new-window", "-d", "-n", f"_bg_{uuid}", "-c", cwd, "claude")
  db.insert_session(Session(id=uuid, tmux_window=f"_bg_{uuid}",
                            cwd=cwd, git_branch=git_branch_of(cwd),
                            started_at=time.time(), title=None))
  switch_to(uuid)  # the two-step swap protocol
  ```
- The session starts as a blank Claude Code (no initial prompt).

### Close confirmation

```
Close "Build REST API"? This kills the Claude Code process.
[y] Yes   [n] No
```

On `y`:
1. If the session being closed is the currently visible one
   (`db.current_session_id == s.id`), first run a "swap to nothing" maneuver:
   create a temporary `_scratch` window with a placeholder shell, then
   `switch_to(scratch)` so the current session's pane returns home; then
   kill its window. Otherwise just kill its window directly.
2. `tmux kill-window -t :_bg_<uuid>`
3. `db.delete_session(uuid)`
4. If `current_session_id` was the closed one, clear it. The right pane now
   shows the placeholder shell from step 1.

### Quit (`:q` + Enter)

Full shutdown of everything:
1. For each session in DB: `tmux kill-window -t :<window>`
2. `tmux kill-session -t task-pilot`
3. Exit the Textual app (process exits)

`:q` is a command-mode sequence modeled after vim: `:` opens a command input,
`q` is the command, `Enter` executes. This is hard enough to mis-type that
no confirmation dialog is needed.

## Platform Support

| Platform                                 | Status       |
|-------------------------------------------|--------------|
| macOS (iTerm2, Terminal.app, Kitty, etc.) | ✅ Supported |
| Linux (any terminal with tmux)            | ✅ Supported |
| WSL2 on Windows                           | ✅ Supported (see notes) |
| Remote Ubuntu via SSH from any OS         | ✅ Recommended |
| VS Code Remote-SSH + integrated terminal  | ✅ Supported |
| Windows native (PowerShell, CMD)          | ❌ Use WSL2  |
| Git Bash on Windows                       | ❌ Use WSL2  |

Minimum requirements:
- Python 3.11+
- tmux 3.0+
- Claude Code CLI installed (`claude` in PATH)
- `psutil` Python package
- UTF-8 terminal with 256 colors

**VS Code Remote-SSH note:** Because pilot uses `:q` (a plain typed sequence)
instead of `Ctrl+Q` to quit, no VS Code terminal configuration is needed. Just
make sure the terminal font supports box-drawing characters and emoji
(`Cascadia Code`, `JetBrains Mono`, or any Nerd Font).

**WSL2 notes:**
- Windows Terminal's mouse-wheel sequences are handled correctly by tmux
  ≥ 3.2 — older versions may behave oddly
- Use a Nerd Font (`Cascadia Code PL`, `MesloLGS NF`) for best Unicode
  rendering of the row separators and status icons

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

These are intentional unknowns to be answered during implementation:

1. **psutil binary children on macOS** — `Process.children(recursive=True)` is
   reliable on Linux but on macOS depends on `libproc`. Does it find a `claude`
   process spawned by a shell inside a tmux pane? Phase 1 will write a focused
   smoke test to verify.

2. **Wheel-up rebind compatibility** — `unbind-key -T root WheelUpPane` should
   prevent copy-mode entry on tmux 3.0+, but Claude Code's TUI may have its own
   wheel handling. Phase 6 will test on the three platforms (macOS Terminal,
   Linux gnome-terminal, VS Code Remote-SSH).

3. **`codex exec` token cost ceiling** — calling `codex exec` once per session
   per 30s could add up if the user has 10+ sessions. Phase 4 may need a
   global rate limit (e.g. at most one `codex exec` call per minute,
   round-robin across sessions that need a title upgrade).

4. **Reconciliation of `current_session_id` when adopted** — if pilot crashed
   while a session was visible in `main.1`, after restart we have a `_bg_*`
   window adopted from tmux but `current_session_id` is unset. The current
   spec says to clear `current_session_id` (right pane shows whatever was in
   `main.1`, possibly the orphan or the placeholder shell). Acceptable but
   means the user might see unexpected content until they click something.

## References

- Previous design (v0.1): `docs/superpowers/plans/2026-03-24-task-pilot.md`
  (deleted after v0.1 shipped; referenced from commit history)
- Similar tools studied during brainstorm:
  - [CCManager](https://github.com/kbwo/ccmanager) — PTY-based, no tmux
  - [Recon](https://github.com/gavraz/recon) — Rust TUI, reads ~/.claude/
  - [claude-session-driver](https://github.com/obra/claude-session-driver) —
    controller/worker pattern over tmux
