"""SQLite persistence for Task Pilot."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from task_pilot.models import Session

# v0.1 tables (tasks, action_items, timeline_events, old sessions) are
# dropped on startup. v0.1 data is not preserved — the spec explicitly
# says "no migration". The `sessions` table here has a different schema
# from v0.1's `sessions` table, so we must drop the old one first.
_V01_TABLES = ("action_items", "timeline_events", "tasks")

SCHEMA_V02 = """
CREATE TABLE IF NOT EXISTS sessions (
    id              TEXT PRIMARY KEY,
    tmux_window     TEXT NOT NULL UNIQUE,
    cwd             TEXT NOT NULL DEFAULT '/',
    git_branch      TEXT,
    started_at      REAL NOT NULL,
    title           TEXT
);

CREATE TABLE IF NOT EXISTS pilot_state (
    key             TEXT PRIMARY KEY,
    value           TEXT
);
"""


def _is_v01_sessions_schema(conn: sqlite3.Connection) -> bool:
    """Return True if `sessions` table has v0.1 columns (session_id, not id)."""
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}
    except sqlite3.OperationalError:
        return False
    return "session_id" in cols and "id" not in cols


class Database:
    def __init__(self, db_path: str | Path):
        self.path = str(db_path)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self._migrate_from_v01()
        self.conn.executescript(SCHEMA_V02)
        self.conn.commit()

    def _migrate_from_v01(self) -> None:
        """Drop any leftover v0.1 tables so the v0.2 schema can be created."""
        # Drop all v0.1-only tables
        for tbl in _V01_TABLES:
            self.conn.execute(f"DROP TABLE IF EXISTS {tbl}")
        # If sessions table has the old schema, drop it too
        if _is_v01_sessions_schema(self.conn):
            self.conn.execute("DROP TABLE IF EXISTS sessions")
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # ── sessions ─────────────────────────────────────────────

    def insert_session(self, s: Session) -> None:
        self.conn.execute(
            """INSERT INTO sessions
               (id, tmux_window, cwd, git_branch, started_at, title)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (s.id, s.tmux_window, s.cwd, s.git_branch, s.started_at, s.title),
        )
        self.conn.commit()

    def get_session(self, session_id: str) -> Session | None:
        row = self.conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        return self._row_to_session(row) if row else None

    def list_sessions(self) -> list[Session]:
        rows = self.conn.execute(
            "SELECT * FROM sessions ORDER BY started_at"
        ).fetchall()
        return [self._row_to_session(r) for r in rows]

    def delete_session(self, session_id: str) -> None:
        self.conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        self.conn.commit()
        if self.get_current_session_id() == session_id:
            self.clear_current_session()

    def update_session(
        self,
        session_id: str,
        *,
        title: str | None = None,
        git_branch: str | None = None,
    ) -> None:
        updates = []
        params = []
        if title is not None:
            updates.append("title = ?")
            params.append(title)
        if git_branch is not None:
            updates.append("git_branch = ?")
            params.append(git_branch)
        if not updates:
            return
        params.append(session_id)
        self.conn.execute(
            f"UPDATE sessions SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        self.conn.commit()

    @staticmethod
    def _row_to_session(row: sqlite3.Row) -> Session:
        return Session(
            id=row["id"],
            tmux_window=row["tmux_window"],
            cwd=row["cwd"],
            git_branch=row["git_branch"],
            started_at=row["started_at"],
            title=row["title"],
        )

    # ── pilot_state ──────────────────────────────────────────

    def set_state(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO pilot_state (key, value) VALUES (?, ?)",
            (key, value),
        )
        self.conn.commit()

    def get_state(self, key: str) -> str | None:
        row = self.conn.execute(
            "SELECT value FROM pilot_state WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None

    def clear_state(self, key: str) -> None:
        self.conn.execute("DELETE FROM pilot_state WHERE key = ?", (key,))
        self.conn.commit()

    # convenience helpers
    def set_current_session_id(self, session_id: str) -> None:
        self.set_state("current_session_id", session_id)

    def get_current_session_id(self) -> str | None:
        return self.get_state("current_session_id")

    def clear_current_session(self) -> None:
        self.clear_state("current_session_id")
