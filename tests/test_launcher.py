import os
from unittest.mock import patch, MagicMock
import pytest
from task_pilot import launcher


def test_pre_flight_passes_when_tmux_and_claude_installed():
    with patch("task_pilot.launcher.shutil.which") as mock_which:
        mock_which.side_effect = lambda b: "/usr/bin/" + b
        launcher.pre_flight_checks()


def test_pre_flight_dies_when_tmux_missing():
    with patch("task_pilot.launcher.shutil.which") as mock_which:
        mock_which.side_effect = lambda b: None if b == "tmux" else "/usr/bin/" + b
        with pytest.raises(SystemExit):
            launcher.pre_flight_checks()


def test_pre_flight_dies_when_claude_missing():
    with patch("task_pilot.launcher.shutil.which") as mock_which:
        mock_which.side_effect = lambda b: None if b == "claude" else "/usr/bin/" + b
        with pytest.raises(SystemExit):
            launcher.pre_flight_checks()


def test_bootstrap_calls_tmux_in_correct_order():
    calls = []
    fakes = {
        "new_session": lambda *a, **kw: calls.append(("new_session", a, kw)),
        "set_option":  lambda *a, **kw: calls.append(("set_option", a, kw)),
        "split_window": lambda *a, **kw: calls.append(("split_window", a, kw)),
        "send_keys":   lambda *a, **kw: calls.append(("send_keys", a, kw)),
        "run":         lambda *a, **kw: calls.append(("run", a, kw)),
    }
    with patch.multiple("task_pilot.launcher.tmux", **fakes):
        launcher.bootstrap_tmux_session()
    op_names = [c[0] for c in calls]
    assert op_names[0] == "new_session"
    assert "split_window" in op_names
    assert "send_keys" in op_names
