import subprocess
import tempfile
from pathlib import Path
from task_pilot.git_branch import current_branch


def test_returns_none_for_non_git_dir(tmp_path):
    assert current_branch(str(tmp_path)) is None


def test_returns_branch_for_git_repo(tmp_path):
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    branch = current_branch(str(tmp_path))
    assert branch == "main"
