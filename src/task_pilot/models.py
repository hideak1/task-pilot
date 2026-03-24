from dataclasses import dataclass, field


@dataclass
class ActionItem:
    id: int
    task_id: str
    description: str
    command: str | None
    is_done: bool
    sort_order: int


@dataclass
class TimelineEvent:
    id: int
    task_id: str
    session_id: str | None
    event_type: str
    description: str
    timestamp: float


@dataclass
class Session:
    session_id: str
    task_id: str
    pid: int | None
    cwd: str | None
    started_at: float
    ended_at: float | None
    is_active: bool
    transcript_path: str | None


@dataclass
class Task:
    id: str
    title: str
    status: str  # pending | action_required | working | done
    summary: str | None
    blocked_reason: str | None
    created_at: float
    updated_at: float
    completed_at: float | None
    sessions: list[Session] = field(default_factory=list)
    action_items: list[ActionItem] = field(default_factory=list)
    timeline: list[TimelineEvent] = field(default_factory=list)
