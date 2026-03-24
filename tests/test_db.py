import os
import tempfile
import time

from task_pilot.db import Database


def make_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return Database(path)


def test_create_and_get_task():
    db = make_db()
    db.upsert_task("t1", title="Test Task", status="pending")
    task = db.get_task("t1")
    assert task is not None
    assert task.title == "Test Task"


def test_upsert_task_updates():
    db = make_db()
    db.upsert_task("t1", title="Old Title", status="pending")
    db.upsert_task("t1", title="New Title", status="working")
    task = db.get_task("t1")
    assert task.title == "New Title"
    assert task.status == "working"


def test_upsert_session():
    db = make_db()
    db.upsert_task("t1", title="Test")
    db.upsert_session("s1", task_id="t1", started_at=time.time())
    task = db.get_task("t1")
    assert len(task.sessions) == 1


def test_add_action_item():
    db = make_db()
    db.upsert_task("t1", title="Test")
    db.add_action_item("t1", "Run train.py on GPU", command="python train.py")
    task = db.get_task("t1")
    assert len(task.action_items) == 1
    assert task.action_items[0].command == "python train.py"


def test_toggle_action_item():
    db = make_db()
    db.upsert_task("t1", title="Test")
    db.add_action_item("t1", "Do thing")
    task = db.get_task("t1")
    item_id = task.action_items[0].id
    db.toggle_action_item(item_id)
    task = db.get_task("t1")
    assert task.action_items[0].is_done


def test_list_tasks_by_status():
    db = make_db()
    db.upsert_task("t1", title="A", status="action_required")
    db.upsert_task("t2", title="B", status="working")
    db.upsert_task("t3", title="C", status="done")
    action = db.list_tasks(status="action_required")
    assert len(action) == 1
    all_tasks = db.list_tasks()
    assert len(all_tasks) == 3


def test_add_timeline_event():
    db = make_db()
    db.upsert_task("t1", title="Test")
    db.upsert_session("s1", task_id="t1", started_at=time.time())
    db.add_timeline_event("t1", session_id="s1", event_type="session_start",
                          description="Session started")
    task = db.get_task("t1")
    assert len(task.timeline) == 1


def test_mark_task_done():
    db = make_db()
    db.upsert_task("t1", title="Test", status="working")
    db.mark_task_done("t1")
    task = db.get_task("t1")
    assert task.status == "done"
    assert task.completed_at is not None


def test_mark_session_inactive():
    db = make_db()
    db.upsert_task("t1", title="Test")
    db.upsert_session("s1", task_id="t1", started_at=time.time())
    db.mark_session_inactive("s1")
    session = db.get_session("s1")
    assert not session.is_active
    assert session.ended_at is not None


def test_get_task_id_for_session():
    db = make_db()
    db.upsert_task("t1", title="Test")
    db.upsert_session("s1", task_id="t1", started_at=time.time())
    assert db.get_task_id_for_session("s1") == "t1"
    assert db.get_task_id_for_session("nonexistent") is None
