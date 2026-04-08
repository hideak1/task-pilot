import os
import tempfile
import time
import pytest
from task_pilot.db import Database
from task_pilot.models import Session


def make_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return Database(path)


def test_insert_and_get_session():
    db = make_db()
    s = Session(
        id="abc", tmux_window="_bg_abc", cwd="/tmp",
        git_branch="main", started_at=time.time(), title="hello",
    )
    db.insert_session(s)
    got = db.get_session("abc")
    assert got is not None
    assert got.id == "abc"
    assert got.title == "hello"


def test_get_session_returns_none_when_missing():
    db = make_db()
    assert db.get_session("nope") is None


def test_list_sessions_returns_all():
    db = make_db()
    for i in range(3):
        db.insert_session(Session(
            id=f"s{i}", tmux_window=f"_bg_s{i}", cwd="/tmp",
            git_branch=None, started_at=time.time() + i, title=None,
        ))
    sessions = db.list_sessions()
    assert len(sessions) == 3
    assert {s.id for s in sessions} == {"s0", "s1", "s2"}


def test_delete_session():
    db = make_db()
    db.insert_session(Session(
        id="x", tmux_window="_bg_x", cwd="/tmp",
        git_branch=None, started_at=0.0, title=None,
    ))
    db.delete_session("x")
    assert db.get_session("x") is None


def test_update_title_and_branch():
    db = make_db()
    db.insert_session(Session(
        id="x", tmux_window="_bg_x", cwd="/tmp",
        git_branch=None, started_at=0.0, title=None,
    ))
    db.update_session("x", title="New title", git_branch="main")
    s = db.get_session("x")
    assert s.title == "New title"
    assert s.git_branch == "main"


def test_pilot_state_set_and_get():
    db = make_db()
    db.set_state("current_session_id", "abc")
    assert db.get_state("current_session_id") == "abc"


def test_pilot_state_returns_none_when_unset():
    db = make_db()
    assert db.get_state("anything") is None


def test_clear_state():
    db = make_db()
    db.set_state("k", "v")
    db.clear_state("k")
    assert db.get_state("k") is None


def test_current_session_helpers():
    db = make_db()
    db.set_current_session_id("abc")
    assert db.get_current_session_id() == "abc"
    db.clear_current_session()
    assert db.get_current_session_id() is None


def test_cwd_default_is_root():
    db = make_db()
    db.insert_session(Session(
        id="x", tmux_window="_bg_x", cwd="/",
        git_branch=None, started_at=0.0, title=None,
    ))
    assert db.get_session("x").cwd == "/"
