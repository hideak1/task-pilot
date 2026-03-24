from pathlib import Path

CLAUDE_HOME = Path.home() / ".claude"
CLAUDE_SESSIONS_DIR = CLAUDE_HOME / "sessions"
CLAUDE_PROJECTS_DIR = CLAUDE_HOME / "projects"
CLAUDE_HISTORY_FILE = CLAUDE_HOME / "history.jsonl"
CLAUDE_SETTINGS_FILE = CLAUDE_HOME / "settings.json"

TASK_PILOT_DIR = Path.home() / ".task-pilot"
DB_PATH = TASK_PILOT_DIR / "tasks.db"

TASK_STATUS_ACTION = "action_required"
TASK_STATUS_WORKING = "working"
TASK_STATUS_DONE = "done"
TASK_STATUS_PENDING = "pending"
