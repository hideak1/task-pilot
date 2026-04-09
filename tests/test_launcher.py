from unittest.mock import patch, MagicMock
import pytest
from task_pilot import launcher


# ── pre_flight_checks ──────────────────────────────────────

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


# ── bootstrap_tmux_session ─────────────────────────────────

def test_bootstrap_full_call_sequence():
    """Verify bootstrap calls tmux operations in the exact required order."""
    calls = []
    fakes = {
        "new_session":  lambda *a, **kw: calls.append(("new_session", a, kw)),
        "set_option":   lambda *a, **kw: calls.append(("set_option", a, kw)),
        "unbind_key":   lambda *a, **kw: calls.append(("unbind_key", a, kw)),
        "split_window": lambda *a, **kw: calls.append(("split_window", a, kw)),
        "send_keys":    lambda *a, **kw: calls.append(("send_keys", a, kw)),
    }
    with patch.multiple("task_pilot.launcher.tmux", **fakes):
        launcher.bootstrap_tmux_session()

    op_names = [c[0] for c in calls]
    # 1. new_session is first (pilot runs in main.0 directly via command arg)
    assert op_names[0] == "new_session"
    # 2. new_session was called with a `command` kwarg running pilot
    ns_call = calls[0]
    ns_kwargs = ns_call[2]
    assert "command" in ns_kwargs
    assert "task_pilot.textual_app" in ns_kwargs["command"]
    # 3. mouse on, status off, both wheel unbinds, split
    assert "set_option" in op_names
    assert op_names.count("unbind_key") == 2
    assert "split_window" in op_names
    # 4. split_window is called with the welcome module command
    sw_calls = [c for c in calls if c[0] == "split_window"]
    assert len(sw_calls) == 1
    sw_kwargs = sw_calls[0][2]
    assert "command" in sw_kwargs
    assert "task_pilot.welcome" in sw_kwargs["command"]
    # 5. unbind_key happens before split_window
    first_unbind = op_names.index("unbind_key")
    first_split = op_names.index("split_window")
    assert first_unbind < first_split


def test_bootstrap_sets_mouse_and_status():
    """Verify the specific set_option calls (mouse on, status off)."""
    calls = []
    fakes = {
        "new_session":  lambda *a, **kw: None,
        "set_option":   lambda *a, **kw: calls.append((a, kw)),
        "unbind_key":   lambda *a, **kw: None,
        "split_window": lambda *a, **kw: None,
        "send_keys":    lambda *a, **kw: None,
    }
    with patch.multiple("task_pilot.launcher.tmux", **fakes):
        launcher.bootstrap_tmux_session()

    # Find mouse and status calls in any form (positional or kwargs)
    set_options = [(a, kw) for (a, kw) in calls]
    flat = [(a + tuple(kw.values()), {**kw}) for (a, kw) in set_options]

    found_mouse = any("mouse" in args and "on" in args for (args, _) in flat)
    found_status = any("status" in args and "off" in args for (args, _) in flat)
    assert found_mouse, f"mouse-on not set: {set_options}"
    assert found_status, f"status-off not set: {set_options}"


def test_bootstrap_unbinds_wheel_keys():
    """Verify wheel-up and wheel-down are unbound from root table."""
    calls = []
    fakes = {
        "new_session":  lambda *a, **kw: None,
        "set_option":   lambda *a, **kw: None,
        "unbind_key":   lambda *a, **kw: calls.append((a, kw)),
        "split_window": lambda *a, **kw: None,
        "send_keys":    lambda *a, **kw: None,
    }
    with patch.multiple("task_pilot.launcher.tmux", **fakes):
        launcher.bootstrap_tmux_session()

    keys_unbound = set()
    for (args, kw) in calls:
        # arg order: table, key
        if len(args) >= 2:
            keys_unbound.add(args[1])
    assert "WheelUpPane" in keys_unbound
    assert "WheelDownPane" in keys_unbound


def test_bootstrap_does_not_use_send_keys():
    """Neither pane uses send_keys — both run their command directly.

    main.0 runs pilot via new_session's command arg; main.1 runs the
    welcome module via split_window's command arg. send_keys was racy
    against shell initialization.
    """
    targets = []
    fakes = {
        "new_session":  lambda *a, **kw: None,
        "set_option":   lambda *a, **kw: None,
        "unbind_key":   lambda *a, **kw: None,
        "split_window": lambda *a, **kw: None,
        "send_keys":    lambda *a, **kw: targets.append(a[0] if a else kw.get("target")),
    }
    with patch.multiple("task_pilot.launcher.tmux", **fakes):
        launcher.bootstrap_tmux_session()

    assert targets == []


# ── get_outer_tmux_session ────────────────────────────────

def test_get_outer_tmux_returns_none_when_not_in_tmux():
    with patch.dict("os.environ", {}, clear=True):
        assert launcher.get_outer_tmux_session() is None


def test_get_outer_tmux_returns_session_name():
    with patch.dict("os.environ", {"TMUX": "/tmp/tmux"}):
        with patch("task_pilot.launcher.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="my-session\n", returncode=0)
            assert launcher.get_outer_tmux_session() == "my-session"


def test_get_outer_tmux_handles_subprocess_error():
    import subprocess as sp
    with patch.dict("os.environ", {"TMUX": "/tmp/tmux"}):
        with patch("task_pilot.launcher.subprocess.run") as mock_run:
            mock_run.side_effect = sp.CalledProcessError(1, "tmux")
            assert launcher.get_outer_tmux_session() is None


# ── main() decision tree ──────────────────────────────────

def test_main_inside_task_pilot_session_runs_textual_app():
    """If we're already inside task-pilot, run the Textual app directly."""
    with patch("task_pilot.launcher.pre_flight_checks"):
        with patch("task_pilot.launcher.get_outer_tmux_session", return_value="task-pilot"):
            with patch("task_pilot.textual_app.main") as mock_textual:
                launcher.main()
                mock_textual.assert_called_once()


def test_main_inside_other_tmux_with_pilot_session_exists_exits():
    with patch("task_pilot.launcher.pre_flight_checks"):
        with patch("task_pilot.launcher.get_outer_tmux_session", return_value="other"):
            with patch("task_pilot.launcher.tmux.has_session", return_value=True):
                with pytest.raises(SystemExit) as exc:
                    launcher.main()
                assert exc.value.code == 1


def test_main_inside_other_tmux_with_no_pilot_session_exits():
    with patch("task_pilot.launcher.pre_flight_checks"):
        with patch("task_pilot.launcher.get_outer_tmux_session", return_value="other"):
            with patch("task_pilot.launcher.tmux.has_session", return_value=False):
                with pytest.raises(SystemExit) as exc:
                    launcher.main()
                assert exc.value.code == 1


def test_main_not_in_tmux_existing_session_attaches():
    """Not in tmux + pilot session exists → execvp tmux attach."""
    with patch("task_pilot.launcher.pre_flight_checks"):
        with patch("task_pilot.launcher.get_outer_tmux_session", return_value=None):
            with patch("task_pilot.launcher.tmux.has_session", return_value=True):
                with patch("task_pilot.launcher.os.execvp") as mock_exec:
                    launcher.main()
                    mock_exec.assert_called_once()
                    args = mock_exec.call_args[0]
                    assert args[0] == "tmux"
                    assert "attach" in args[1]


def test_main_not_in_tmux_no_session_bootstraps_then_attaches():
    """Not in tmux + no pilot session → bootstrap then attach."""
    with patch("task_pilot.launcher.pre_flight_checks"):
        with patch("task_pilot.launcher.get_outer_tmux_session", return_value=None):
            with patch("task_pilot.launcher.tmux.has_session", return_value=False):
                with patch("task_pilot.launcher.bootstrap_tmux_session") as mock_boot:
                    with patch("task_pilot.launcher.os.execvp") as mock_exec:
                        launcher.main()
                        mock_boot.assert_called_once()
                        mock_exec.assert_called_once()


# ── cmd_kill ──────────────────────────────────────────────

def test_cmd_kill_when_session_exists():
    with patch("task_pilot.launcher.tmux.has_session", return_value=True):
        with patch("task_pilot.launcher.tmux.kill_session") as mock_kill:
            launcher.cmd_kill()
            mock_kill.assert_called_once_with("task-pilot")


def test_cmd_kill_when_no_session():
    with patch("task_pilot.launcher.tmux.has_session", return_value=False):
        with patch("task_pilot.launcher.tmux.kill_session") as mock_kill:
            launcher.cmd_kill()
            mock_kill.assert_not_called()
