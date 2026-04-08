from unittest.mock import patch, MagicMock
import pytest
from task_pilot import tmux


def test_run_calls_subprocess():
    with patch("task_pilot.tmux.subprocess.run") as mock:
        mock.return_value = MagicMock(returncode=0, stdout="ok\n", stderr="")
        result = tmux.run(["list-sessions"])
        mock.assert_called_once()
        assert result.stdout == "ok\n"


def test_has_session_true():
    with patch("task_pilot.tmux.run") as mock:
        mock.return_value = MagicMock(returncode=0, stdout="", stderr="")
        assert tmux.has_session("task-pilot") is True


def test_has_session_false():
    with patch("task_pilot.tmux.run") as mock:
        mock.return_value = MagicMock(returncode=1, stdout="", stderr="no such session")
        assert tmux.has_session("task-pilot") is False


def test_list_windows_filters_format():
    with patch("task_pilot.tmux.run") as mock:
        mock.return_value = MagicMock(
            returncode=0,
            stdout="main\n_bg_abc123\n_bg_def456\n",
            stderr="",
        )
        windows = tmux.list_windows("task-pilot")
        assert windows == ["main", "_bg_abc123", "_bg_def456"]


def test_window_exists_true():
    with patch("task_pilot.tmux.list_windows") as mock:
        mock.return_value = ["main", "_bg_abc"]
        assert tmux.window_exists("task-pilot", "main") is True


def test_window_exists_false():
    with patch("task_pilot.tmux.list_windows") as mock:
        mock.return_value = ["main"]
        assert tmux.window_exists("task-pilot", "_bg_xxx") is False


def test_new_session_calls_correct_args():
    with patch("task_pilot.tmux.run") as mock:
        mock.return_value = MagicMock(returncode=0)
        tmux.new_session("task-pilot")
        args = mock.call_args[0][0]
        assert args[:3] == ["new-session", "-d", "-s"]
        assert "task-pilot" in args


def test_split_window_horizontal_70_percent():
    with patch("task_pilot.tmux.run") as mock:
        mock.return_value = MagicMock(returncode=0)
        tmux.split_window("task-pilot:main", percent=70)
        args = mock.call_args[0][0]
        assert "-h" in args
        assert "70%" in args


def test_swap_pane_calls_correct_args():
    with patch("task_pilot.tmux.run") as mock:
        mock.return_value = MagicMock(returncode=0)
        tmux.swap_pane("task-pilot:main.1", "task-pilot:_bg_abc.0")
        args = mock.call_args[0][0]
        assert args[0] == "swap-pane"
        assert "-s" in args
        assert "-t" in args


def test_kill_window_passes_target():
    with patch("task_pilot.tmux.run") as mock:
        mock.return_value = MagicMock(returncode=0)
        tmux.kill_window("task-pilot:_bg_xyz")
        args = mock.call_args[0][0]
        assert args == ["kill-window", "-t", "task-pilot:_bg_xyz"]


def test_send_keys_with_enter():
    with patch("task_pilot.tmux.run") as mock:
        mock.return_value = MagicMock(returncode=0)
        tmux.send_keys("task-pilot:main.0", "echo hi")
        args = mock.call_args[0][0]
        assert args == ["send-keys", "-t", "task-pilot:main.0", "echo hi", "Enter"]


def test_display_message_returns_stripped():
    with patch("task_pilot.tmux.run") as mock:
        mock.return_value = MagicMock(returncode=0, stdout="/home/user\n", stderr="")
        result = tmux.display_message("task-pilot:_bg_x.0", "#{pane_current_path}")
        assert result == "/home/user"
