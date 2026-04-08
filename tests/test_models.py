from pathlib import Path
import time
from task_pilot.models import Session, SessionState


def test_session_creation():
    s = Session(
        id="abc123",
        tmux_window="_bg_abc123",
        cwd="/tmp/proj",
        git_branch="main",
        started_at=time.time(),
        title=None,
    )
    assert s.id == "abc123"
    assert s.git_branch == "main"


def test_session_optional_fields_default_to_none():
    s = Session(
        id="x",
        tmux_window="_bg_x",
        cwd="/tmp",
        git_branch=None,
        started_at=0.0,
        title=None,
    )
    assert s.title is None
    assert s.git_branch is None


def test_session_state_defaults():
    state = SessionState(session_id="abc")
    assert state.is_alive is True
    assert state.token_count == 0
    assert state.status == "initializing"
    assert state.transcript_path is None


def test_session_state_with_values():
    state = SessionState(
        session_id="abc",
        is_alive=True,
        last_activity=12345.0,
        token_count=4500,
        claude_session_id="claude-uuid",
        transcript_path=Path("/tmp/x.jsonl"),
        status="working",
    )
    assert state.token_count == 4500
    assert state.status == "working"
