import os
import tempfile
from pathlib import Path
from task_pilot.widgets.new_session_dialog import complete_path, recent_directories


def test_complete_path_single_match(tmp_path, monkeypatch):
    (tmp_path / "alpha").mkdir()
    monkeypatch.setenv("HOME", str(tmp_path))
    result = complete_path(str(tmp_path / "alp"))
    assert result.endswith("alpha/")


def test_complete_path_multiple_match(tmp_path):
    (tmp_path / "alpha").mkdir()
    (tmp_path / "alphabet").mkdir()
    result = complete_path(str(tmp_path / "alp"))
    assert result.endswith("alpha")  # common prefix
