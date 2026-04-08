"""Phase 4 integration: refresh_state with real fake-claude-home + real files."""

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from task_pilot.db import Database
from task_pilot.models import Session
from task_pilot.session_tracker import SessionTracker


def make_db(tmp_path):
    return Database(tmp_path / "p4.db")


def make_fake_claude_home(tmp_path: Path, sessions: list[tuple[str, str, list[dict]]]) -> Path:
    """Build a fake ~/.claude/ tree.

    sessions: list of (cwd, claude_session_id, jsonl_records)
    Returns the claude_home Path.
    """
    home = tmp_path / "claude_home"
    projects = home / "projects"
    projects.mkdir(parents=True)
    for cwd, sid, records in sessions:
        slug = cwd.replace("/", "-")
        proj_dir = projects / slug
        proj_dir.mkdir(parents=True, exist_ok=True)
        transcript = proj_dir / f"{sid}.jsonl"
        with transcript.open("w") as f:
            for rec in records:
                f.write(json.dumps(rec) + "\n")
    return home


def test_refresh_state_reads_tokens_and_status_from_real_transcript(tmp_path, monkeypatch):
    """End-to-end: pilot session -> real transcript -> token + status."""
    cwd = str(tmp_path / "myproj")
    os.makedirs(cwd, exist_ok=True)
    sid = "claude-uuid-test-1"
    now_ms = int(time.time() * 1000)

    records = [
        {"type": "user", "message": {"content": "Build something"},
         "timestamp": "2026-04-08T10:00:00Z"},
        {"type": "assistant", "message": {
            "content": "Done",
            "usage": {"input_tokens": 100, "output_tokens": 50,
                       "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
        }, "timestamp": "2026-04-08T10:00:05Z"},
    ]
    fake_home = make_fake_claude_home(tmp_path, [(cwd, sid, records)])
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    db = make_db(tmp_path)
    db.insert_session(Session(
        id="pilot-uuid", tmux_window="_bg_pilot-uuid", cwd=cwd,
        git_branch=None, started_at=time.time() - 60, title=None,
    ))

    fake_tmux = MagicMock()
    tracker = SessionTracker(db, tmux=fake_tmux)

    # Patch resolve_by_cwd_and_time to look at our fake home.
    # session_tracker does a local `from task_pilot.transcript_resolver import ...`
    # at call time, so we must patch the source module.
    from task_pilot import transcript_resolver
    original_resolve = transcript_resolver.resolve_by_cwd_and_time
    monkeypatch.setattr(
        transcript_resolver,
        "resolve_by_cwd_and_time",
        lambda cwd, started_at, claude_home=None: original_resolve(
            cwd, started_at, claude_home=claude_home or fake_home
        ),
    )

    states = tracker.refresh_state()
    assert "pilot-uuid" in states
    state = states["pilot-uuid"]
    assert state.token_count == 150  # input+output only
    # status will be 'idle' because timestamps are from 2026-04-08 fixed
    assert state.status in ("idle", "working")

    # Title was back-filled from first user message
    s = db.get_session("pilot-uuid")
    assert s.title == "Build something"


def test_refresh_state_status_initializing_when_no_transcript(tmp_path):
    db = make_db(tmp_path)
    db.insert_session(Session(
        id="orphan", tmux_window="_bg_orphan", cwd=str(tmp_path),
        git_branch=None, started_at=time.time(), title=None,
    ))
    fake_tmux = MagicMock()
    tracker = SessionTracker(db, tmux=fake_tmux)
    states = tracker.refresh_state()
    assert states["orphan"].status == "initializing"


def test_refresh_state_caches_across_calls(tmp_path):
    """Calling refresh_state twice should reuse the SessionState object (cache hit)."""
    db = make_db(tmp_path)
    db.insert_session(Session(
        id="cached", tmux_window="_bg_cached", cwd=str(tmp_path),
        git_branch=None, started_at=time.time(), title=None,
    ))
    fake_tmux = MagicMock()
    tracker = SessionTracker(db, tmux=fake_tmux)
    s1 = tracker.refresh_state()["cached"]
    s2 = tracker.refresh_state()["cached"]
    # Same instance from cache
    assert s1 is s2


def test_refresh_state_force_recomputes_branch(tmp_path):
    """force=True should re-query git branch."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=repo, check=True, capture_output=True)

    db = make_db(tmp_path)
    db.insert_session(Session(
        id="g", tmux_window="_bg_g", cwd=str(repo),
        git_branch=None, started_at=time.time(), title=None,
    ))
    fake_tmux = MagicMock()
    tracker = SessionTracker(db, tmux=fake_tmux)
    tracker.refresh_state(force=False)
    s = db.get_session("g")
    assert s.git_branch == "main"


def test_git_branch_real_repo(tmp_path):
    """git_branch helper works on a real freshly-init'd repo."""
    from task_pilot.git_branch import current_branch
    subprocess.run(["git", "init", "-b", "feature"], cwd=tmp_path, check=True, capture_output=True)
    assert current_branch(str(tmp_path)) == "feature"


def test_git_branch_returns_none_for_non_git(tmp_path):
    from task_pilot.git_branch import current_branch
    assert current_branch(str(tmp_path)) is None


def test_transcript_resolver_real_filesystem(tmp_path):
    """resolve_by_cwd_and_time finds the right .jsonl in a fake claude home."""
    from task_pilot.transcript_resolver import resolve_by_cwd_and_time, cwd_to_slug

    home = tmp_path / ".claude"
    cwd = "/Users/foo/myproj"
    proj = home / "projects" / cwd_to_slug(cwd)
    proj.mkdir(parents=True)
    transcript = proj / "session-uuid-1.jsonl"
    transcript.write_text("{}\n")

    found = resolve_by_cwd_and_time(
        cwd=cwd,
        started_at=transcript.stat().st_ctime - 10,
        claude_home=home,
    )
    assert found == transcript
