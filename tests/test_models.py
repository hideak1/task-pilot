import time
from task_pilot.models import Task, Session, ActionItem, TimelineEvent


def test_task_creation():
    t = Task(
        id="abc", title="Test", status="pending", summary=None,
        blocked_reason=None, created_at=time.time(), updated_at=time.time(),
        completed_at=None, sessions=[], action_items=[], timeline=[],
    )
    assert t.status == "pending"
    assert t.sessions == []


def test_action_item_defaults():
    a = ActionItem(
        id=1, task_id="abc", description="Do thing",
        command="echo hi", is_done=False, sort_order=0,
    )
    assert not a.is_done
    assert a.command == "echo hi"


def test_session_creation():
    s = Session(
        session_id="s1", task_id="abc", pid=1234, cwd="/tmp",
        started_at=time.time(), ended_at=None, is_active=True,
        transcript_path=None,
    )
    assert s.is_active
    assert s.ended_at is None


def test_timeline_event():
    e = TimelineEvent(
        id=1, task_id="abc", session_id="s1",
        event_type="session_start", description="Started",
        timestamp=time.time(),
    )
    assert e.event_type == "session_start"


def test_task_with_relations():
    now = time.time()
    session = Session("s1", "t1", 100, "/tmp", now, None, True, None)
    item = ActionItem(1, "t1", "Run tests", "pytest", False, 0)
    event = TimelineEvent(1, "t1", "s1", "session_start", "Started", now)
    task = Task(
        id="t1", title="Build API", status="working",
        summary="Building REST API", blocked_reason=None,
        created_at=now, updated_at=now, completed_at=None,
        sessions=[session], action_items=[item], timeline=[event],
    )
    assert len(task.sessions) == 1
    assert len(task.action_items) == 1
    assert len(task.timeline) == 1
