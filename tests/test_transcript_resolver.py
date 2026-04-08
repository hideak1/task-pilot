import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
from task_pilot.transcript_resolver import (
    cwd_to_slug,
    resolve_by_cwd_and_time,
)


def test_cwd_to_slug():
    assert cwd_to_slug("/Users/foo/proj") == "-Users-foo-proj"
    assert cwd_to_slug("/tmp/x") == "-tmp-x"


def test_resolve_by_cwd_and_time(tmp_path):
    # Set up fake claude home
    claude_home = tmp_path / ".claude"
    proj_dir = claude_home / "projects" / "-tmp-myproj"
    proj_dir.mkdir(parents=True)
    transcript = proj_dir / "session-uuid-123.jsonl"
    transcript.write_text("{}\n")

    found = resolve_by_cwd_and_time(
        cwd="/tmp/myproj",
        started_at=transcript.stat().st_ctime - 10,
        claude_home=claude_home,
    )
    assert found == transcript


def test_resolve_by_cwd_returns_none_when_no_dir(tmp_path):
    claude_home = tmp_path / ".claude"
    found = resolve_by_cwd_and_time("/tmp/nope", 0, claude_home)
    assert found is None
