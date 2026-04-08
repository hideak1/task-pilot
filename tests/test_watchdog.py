"""Tests for the --watchdog wrapper in textual_app.main()."""

from __future__ import annotations

from unittest.mock import patch

from task_pilot import textual_app


def test_main_without_watchdog_flag():
    with patch.object(textual_app.TaskPilotTextualApp, "run", return_value=None) as run, \
         patch("sys.argv", ["task-pilot"]):
        textual_app.main()
    assert run.call_count == 1


def test_main_with_watchdog_recovers_from_one_crash():
    calls = {"n": 0}

    def fake_run(self):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return None

    with patch.object(textual_app.TaskPilotTextualApp, "run", fake_run), \
         patch("sys.argv", ["task-pilot", "--watchdog"]), \
         patch("time.sleep"):
        textual_app.main()
    assert calls["n"] == 2


def test_main_with_watchdog_gives_up_after_three_crashes():
    calls = {"n": 0}

    def fake_run(self):
        calls["n"] += 1
        raise RuntimeError("boom")

    with patch.object(textual_app.TaskPilotTextualApp, "run", fake_run), \
         patch("sys.argv", ["task-pilot", "--watchdog"]), \
         patch("time.sleep"):
        textual_app.main()
    assert calls["n"] == 3
