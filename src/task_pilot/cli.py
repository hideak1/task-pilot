import os

import click

from task_pilot.config import CLAUDE_SETTINGS_FILE, DB_PATH, TASK_PILOT_DIR


@click.group()
def main():
    """Task Pilot - Claude Code session dispatcher panel."""
    TASK_PILOT_DIR.mkdir(parents=True, exist_ok=True)


@main.command()
def ui():
    """Launch the TUI dashboard."""
    from task_pilot.app import TaskPilotApp

    app = TaskPilotApp()
    app.run()


@main.command()
def scan():
    """Scan Claude Code sessions and sync to DB."""
    from task_pilot.db import Database
    from task_pilot.scanner import ClaudeScanner

    db = Database(DB_PATH)
    scanner = ClaudeScanner(db=db)
    scanner.scan()
    click.echo("Scan complete.")


@main.command(name="install-hooks")
def install_hooks():
    """Install Claude Code hooks for real-time tracking."""
    from task_pilot.hooks import HookInstaller

    installer = HookInstaller(settings_path=CLAUDE_SETTINGS_FILE)
    installer.install()
    click.echo("Hooks installed.")


@main.group()
def hook():
    """Hook handlers (called by Claude Code, not by users)."""
    pass


@hook.command(name="session-start")
def hook_session_start():
    """Handle SessionStart hook event."""
    from task_pilot.db import Database
    from task_pilot.hooks import handle_session_start

    db = Database(DB_PATH)
    handle_session_start(
        db=db,
        session_id=os.environ.get("CLAUDE_SESSION_ID", os.environ.get("SESSION_ID", "")),
        project_dir=os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()),
        pid=os.getppid(),
    )


@hook.command(name="session-end")
def hook_session_end():
    """Handle SessionEnd hook event."""
    from task_pilot.db import Database
    from task_pilot.hooks import handle_session_end

    db = Database(DB_PATH)
    handle_session_end(
        db=db,
        session_id=os.environ.get("CLAUDE_SESSION_ID", os.environ.get("SESSION_ID", "")),
    )


@hook.command(name="heartbeat")
def hook_heartbeat():
    """Handle PostToolUse hook - marks session as actively working."""
    from task_pilot.db import Database
    from task_pilot.hooks import handle_heartbeat

    db = Database(DB_PATH)
    handle_heartbeat(
        db=db,
        session_id=os.environ.get("CLAUDE_SESSION_ID", os.environ.get("SESSION_ID", "")),
    )


@hook.command(name="stop")
def hook_stop():
    """Handle Stop hook - user interrupted, likely needs human action."""
    from task_pilot.db import Database
    from task_pilot.hooks import handle_stop

    db = Database(DB_PATH)
    handle_stop(
        db=db,
        session_id=os.environ.get("CLAUDE_SESSION_ID", os.environ.get("SESSION_ID", "")),
    )
