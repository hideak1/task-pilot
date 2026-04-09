import time
from task_pilot.models import Session, SessionState
from task_pilot.widgets.session_row import SessionRow, format_elapsed, format_tokens, abbrev_home


def test_format_elapsed_seconds():
    assert format_elapsed(45) == "45s"


def test_format_elapsed_minutes():
    assert format_elapsed(23 * 60) == "23m"


def test_format_elapsed_hours():
    assert format_elapsed(2 * 3600 + 15 * 60) == "2h 15m"


def test_format_tokens_thousands():
    assert format_tokens(45000) == "45k"
    assert format_tokens(999) == "999"
    assert format_tokens(1500) == "1.5k"


def test_abbrev_home(monkeypatch):
    monkeypatch.setenv("HOME", "/Users/foo")
    assert abbrev_home("/Users/foo/project") == "~/project"
    assert abbrev_home("/tmp/x") == "/tmp/x"


def test_session_row_can_be_constructed():
    s = Session(
        id="abc", tmux_window="_bg_abc", cwd="/tmp",
        git_branch="main", started_at=time.time() - 60, title="Test session",
    )
    state = SessionState(session_id="abc", token_count=1234, status="working")
    row = SessionRow(session=s, state=state, selected=False)
    assert row.session_data is s
    assert row.session_state is state
