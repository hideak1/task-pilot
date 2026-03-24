import json
import os
import tempfile

from click.testing import CliRunner

from task_pilot.cli import main


def test_cli_help():
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "Task Pilot" in result.output


def test_cli_scan_command(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr("task_pilot.cli.DB_PATH", db_path)
    monkeypatch.setattr("task_pilot.cli.TASK_PILOT_DIR", tmp_path)
    runner = CliRunner()
    result = runner.invoke(main, ["scan"])
    assert result.exit_code == 0
    assert "Scan complete" in result.output


def test_cli_install_hooks(tmp_path, monkeypatch):
    settings_path = tmp_path / "settings.json"
    settings_path.write_text("{}")
    monkeypatch.setattr("task_pilot.cli.CLAUDE_SETTINGS_FILE", settings_path)
    monkeypatch.setattr("task_pilot.cli.TASK_PILOT_DIR", tmp_path)
    runner = CliRunner()
    result = runner.invoke(main, ["install-hooks"])
    assert result.exit_code == 0
    assert "Hooks installed" in result.output
    settings = json.loads(settings_path.read_text())
    assert "hooks" in settings


def test_cli_hook_session_start(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr("task_pilot.cli.DB_PATH", db_path)
    monkeypatch.setattr("task_pilot.cli.TASK_PILOT_DIR", tmp_path)
    monkeypatch.setenv("CLAUDE_SESSION_ID", "test-session-123")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/tmp/myproject")
    runner = CliRunner()
    result = runner.invoke(main, ["hook", "session-start"])
    assert result.exit_code == 0


def test_cli_hook_session_end(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr("task_pilot.cli.DB_PATH", db_path)
    monkeypatch.setattr("task_pilot.cli.TASK_PILOT_DIR", tmp_path)
    monkeypatch.setenv("CLAUDE_SESSION_ID", "test-session-456")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/tmp/myproject")
    runner = CliRunner()
    # Start first so session exists
    runner.invoke(main, ["hook", "session-start"])
    result = runner.invoke(main, ["hook", "session-end"])
    assert result.exit_code == 0


def test_cli_hook_heartbeat(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr("task_pilot.cli.DB_PATH", db_path)
    monkeypatch.setattr("task_pilot.cli.TASK_PILOT_DIR", tmp_path)
    monkeypatch.setenv("CLAUDE_SESSION_ID", "test-session-789")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/tmp/myproject")
    runner = CliRunner()
    runner.invoke(main, ["hook", "session-start"])
    result = runner.invoke(main, ["hook", "heartbeat"])
    assert result.exit_code == 0


def test_cli_hook_stop(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr("task_pilot.cli.DB_PATH", db_path)
    monkeypatch.setattr("task_pilot.cli.TASK_PILOT_DIR", tmp_path)
    monkeypatch.setenv("CLAUDE_SESSION_ID", "test-session-abc")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/tmp/myproject")
    runner = CliRunner()
    runner.invoke(main, ["hook", "session-start"])
    result = runner.invoke(main, ["hook", "stop"])
    assert result.exit_code == 0


def test_cli_hook_group_help():
    runner = CliRunner()
    result = runner.invoke(main, ["hook", "--help"])
    assert result.exit_code == 0
    assert "session-start" in result.output
    assert "session-end" in result.output
    assert "heartbeat" in result.output
    assert "stop" in result.output
