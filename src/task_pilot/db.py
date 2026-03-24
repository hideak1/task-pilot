import sqlite3
import time
import uuid
from pathlib import Path

from task_pilot.models import ActionItem, Session, Task, TimelineEvent

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    summary     TEXT,
    blocked_reason TEXT,
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL,
    completed_at REAL
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id    TEXT PRIMARY KEY,
    task_id       TEXT NOT NULL REFERENCES tasks(id),
    pid           INTEGER,
    cwd           TEXT,
    started_at    REAL NOT NULL,
    ended_at      REAL,
    is_active     INTEGER DEFAULT 0,
    transcript_path TEXT
);

CREATE TABLE IF NOT EXISTS action_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     TEXT NOT NULL REFERENCES tasks(id),
    description TEXT NOT NULL,
    command     TEXT,
    is_done     INTEGER DEFAULT 0,
    sort_order  INTEGER DEFAULT 0,
    created_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS timeline_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     TEXT NOT NULL REFERENCES tasks(id),
    session_id  TEXT REFERENCES sessions(session_id),
    event_type  TEXT NOT NULL,
    description TEXT NOT NULL,
    timestamp   REAL NOT NULL
);
"""


class Database:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self):
        self.conn.close()

    def upsert_task(
        self,
        task_id: str,
        title: str = "Untitled",
        status: str = "pending",
        summary: str | None = None,
        blocked_reason: str | None = None,
    ):
        now = time.time()
        existing = self.conn.execute(
            "SELECT id FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if existing:
            self.conn.execute(
                """UPDATE tasks SET title = COALESCE(?, title),
                   status = ?, summary = COALESCE(?, summary),
                   blocked_reason = ?, updated_at = ?
                   WHERE id = ?""",
                (title, status, summary, blocked_reason, now, task_id),
            )
        else:
            self.conn.execute(
                """INSERT INTO tasks (id, title, status, summary, blocked_reason, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (task_id, title, status, summary, blocked_reason, now, now),
            )
        self.conn.commit()

    def get_task(self, task_id: str) -> Task | None:
        row = self.conn.execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if not row:
            return None
        sessions = self._get_sessions(task_id)
        action_items = self._get_action_items(task_id)
        timeline = self._get_timeline(task_id)
        return Task(
            id=row["id"],
            title=row["title"],
            status=row["status"],
            summary=row["summary"],
            blocked_reason=row["blocked_reason"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            completed_at=row["completed_at"],
            sessions=sessions,
            action_items=action_items,
            timeline=timeline,
        )

    def list_tasks(self, status: str | None = None) -> list[Task]:
        if status:
            rows = self.conn.execute(
                "SELECT id FROM tasks WHERE status = ? ORDER BY updated_at DESC",
                (status,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT id FROM tasks ORDER BY updated_at DESC"
            ).fetchall()
        return [self.get_task(r["id"]) for r in rows]

    def upsert_session(
        self,
        session_id: str,
        task_id: str,
        started_at: float | None = None,
        ended_at: float | None = None,
        pid: int | None = None,
        cwd: str | None = None,
        is_active: bool = True,
        transcript_path: str | None = None,
    ):
        now = time.time()
        if started_at is None:
            started_at = now
        existing = self.conn.execute(
            "SELECT session_id FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if existing:
            self.conn.execute(
                """UPDATE sessions SET task_id = ?, pid = COALESCE(?, pid),
                   cwd = COALESCE(?, cwd), ended_at = ?, is_active = ?,
                   transcript_path = COALESCE(?, transcript_path)
                   WHERE session_id = ?""",
                (task_id, pid, cwd, ended_at, int(is_active), transcript_path, session_id),
            )
        else:
            self.conn.execute(
                """INSERT INTO sessions (session_id, task_id, pid, cwd, started_at, ended_at, is_active, transcript_path)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (session_id, task_id, pid, cwd, started_at, ended_at, int(is_active), transcript_path),
            )
        self.conn.commit()

    def add_action_item(
        self, task_id: str, description: str, command: str | None = None
    ) -> int:
        now = time.time()
        max_order = self.conn.execute(
            "SELECT COALESCE(MAX(sort_order), -1) FROM action_items WHERE task_id = ?",
            (task_id,),
        ).fetchone()[0]
        cursor = self.conn.execute(
            """INSERT INTO action_items (task_id, description, command, sort_order, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (task_id, description, command, max_order + 1, now),
        )
        self.conn.commit()
        return cursor.lastrowid

    def toggle_action_item(self, item_id: int):
        self.conn.execute(
            "UPDATE action_items SET is_done = 1 - is_done WHERE id = ?",
            (item_id,),
        )
        self.conn.commit()

    def add_timeline_event(
        self,
        task_id: str,
        session_id: str | None = None,
        event_type: str = "session_start",
        description: str = "",
    ) -> int:
        now = time.time()
        cursor = self.conn.execute(
            """INSERT INTO timeline_events (task_id, session_id, event_type, description, timestamp)
               VALUES (?, ?, ?, ?, ?)""",
            (task_id, session_id, event_type, description, now),
        )
        self.conn.commit()
        return cursor.lastrowid

    def mark_task_done(self, task_id: str):
        now = time.time()
        self.conn.execute(
            "UPDATE tasks SET status = 'done', completed_at = ?, updated_at = ? WHERE id = ?",
            (now, now, task_id),
        )
        self.conn.commit()

    def mark_session_inactive(self, session_id: str):
        now = time.time()
        self.conn.execute(
            "UPDATE sessions SET is_active = 0, ended_at = COALESCE(ended_at, ?) WHERE session_id = ?",
            (now, session_id),
        )
        self.conn.commit()

    def update_task_status(self, task_id: str, status: str):
        now = time.time()
        self.conn.execute(
            "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
            (status, now, task_id),
        )
        self.conn.commit()

    def get_session(self, session_id: str) -> Session | None:
        row = self.conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_session(row)

    def get_task_id_for_session(self, session_id: str) -> str | None:
        row = self.conn.execute(
            "SELECT task_id FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        return row["task_id"] if row else None

    def _get_sessions(self, task_id: str) -> list[Session]:
        rows = self.conn.execute(
            "SELECT * FROM sessions WHERE task_id = ? ORDER BY started_at DESC",
            (task_id,),
        ).fetchall()
        return [self._row_to_session(r) for r in rows]

    def _get_action_items(self, task_id: str) -> list[ActionItem]:
        rows = self.conn.execute(
            "SELECT * FROM action_items WHERE task_id = ? ORDER BY sort_order",
            (task_id,),
        ).fetchall()
        return [
            ActionItem(
                id=r["id"],
                task_id=r["task_id"],
                description=r["description"],
                command=r["command"],
                is_done=bool(r["is_done"]),
                sort_order=r["sort_order"],
            )
            for r in rows
        ]

    def _get_timeline(self, task_id: str) -> list[TimelineEvent]:
        rows = self.conn.execute(
            "SELECT * FROM timeline_events WHERE task_id = ? ORDER BY timestamp",
            (task_id,),
        ).fetchall()
        return [
            TimelineEvent(
                id=r["id"],
                task_id=r["task_id"],
                session_id=r["session_id"],
                event_type=r["event_type"],
                description=r["description"],
                timestamp=r["timestamp"],
            )
            for r in rows
        ]

    def _row_to_session(self, r) -> Session:
        return Session(
            session_id=r["session_id"],
            task_id=r["task_id"],
            pid=r["pid"],
            cwd=r["cwd"],
            started_at=r["started_at"],
            ended_at=r["ended_at"],
            is_active=bool(r["is_active"]),
            transcript_path=r["transcript_path"],
        )
