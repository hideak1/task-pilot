"""Tests for the Summarizer class."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from task_pilot.summarizer import Summarizer


def make_transcript(tmp_path: Path, entries: list[dict]) -> Path:
    """Write entries as a .jsonl file and return its path."""
    path = tmp_path / "transcript.jsonl"
    lines = [json.dumps(e) for e in entries]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# from_transcript
# ---------------------------------------------------------------------------

def test_heuristic_summary(tmp_path: Path) -> None:
    path = make_transcript(tmp_path, [
        {"type": "user", "message": {"content": "Build a REST API for user management"}},
        {"type": "assistant", "message": {"content": "I'll create the API with Flask..."}},
        {"type": "tool_use", "tool": "Write", "input": {"file_path": "/tmp/app.py"}},
        {"type": "assistant", "message": {"content": "Done! I've created app.py with endpoints for CRUD."}},
    ])
    summarizer = Summarizer()
    # Force heuristic path by mocking claude CLI to fail
    with patch.object(summarizer, "_try_claude_cli", return_value=None):
        summary = summarizer.from_transcript(path)
    assert summary is not None
    assert len(summary) > 0
    assert "REST API" in summary
    assert "CRUD" in summary


def test_from_transcript_uses_claude_when_available(tmp_path: Path) -> None:
    path = make_transcript(tmp_path, [
        {"type": "user", "message": {"content": "Hello"}},
        {"type": "assistant", "message": {"content": "Hi there"}},
    ])
    summarizer = Summarizer()
    with patch.object(summarizer, "_try_claude_cli", return_value="Claude summary"):
        summary = summarizer.from_transcript(path)
    assert summary == "Claude summary"


# ---------------------------------------------------------------------------
# extract_action_items
# ---------------------------------------------------------------------------

def test_extract_action_items_from_transcript(tmp_path: Path) -> None:
    path = make_transcript(tmp_path, [
        {"type": "user", "message": {"content": "Train the model"}},
        {"type": "assistant", "message": {"content": (
            "I wrote train.py. You need to:\n"
            "1. scp train.py to GPU server\n"
            "2. Run python train.py\n"
            "3. Copy model.pt back"
        )}},
    ])
    summarizer = Summarizer()
    items = summarizer.extract_action_items(path)
    assert len(items) >= 2
    # Verify specific items were found
    combined = " ".join(items)
    assert "scp" in combined.lower()
    assert "train.py" in combined


def test_extract_action_items_empty(tmp_path: Path) -> None:
    path = make_transcript(tmp_path, [
        {"type": "user", "message": {"content": "Hello"}},
        {"type": "assistant", "message": {"content": "Hi, how can I help?"}},
    ])
    summarizer = Summarizer()
    items = summarizer.extract_action_items(path)
    assert items == []


def test_extract_action_items_please_run(tmp_path: Path) -> None:
    path = make_transcript(tmp_path, [
        {"type": "assistant", "message": {"content": "Please run `pytest` to verify everything works."}},
    ])
    summarizer = Summarizer()
    items = summarizer.extract_action_items(path)
    assert len(items) >= 1
    assert any("pytest" in item for item in items)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_empty_transcript(tmp_path: Path) -> None:
    path = tmp_path / "empty.jsonl"
    path.write_text("")
    summarizer = Summarizer()
    summary = summarizer.from_transcript(path)
    assert summary is None


def test_missing_file(tmp_path: Path) -> None:
    path = tmp_path / "nonexistent.jsonl"
    summarizer = Summarizer()
    summary = summarizer.from_transcript(path)
    assert summary is None


def test_malformed_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text("not json\n{bad json too\n", encoding="utf-8")
    summarizer = Summarizer()
    summary = summarizer.from_transcript(path)
    assert summary is None  # no valid messages parsed


# ---------------------------------------------------------------------------
# _parse_transcript
# ---------------------------------------------------------------------------

def test_parse_transcript(tmp_path: Path) -> None:
    entries = [
        {"type": "user", "message": {"content": "Hello"}},
        {"type": "assistant", "message": {"content": "Hi"}},
        {"type": "tool_use", "tool": "Read", "input": {"file_path": "/tmp/x"}},
    ]
    path = make_transcript(tmp_path, entries)
    summarizer = Summarizer()
    messages = summarizer._parse_transcript(path)
    assert len(messages) == 3
    assert messages[0]["type"] == "user"
    assert messages[1]["type"] == "assistant"
    assert messages[2]["type"] == "tool_use"


def test_parse_transcript_skips_blank_lines(tmp_path: Path) -> None:
    path = tmp_path / "transcript.jsonl"
    path.write_text(
        '{"type": "user", "message": {"content": "Hi"}}\n\n\n'
        '{"type": "assistant", "message": {"content": "Hello"}}\n',
        encoding="utf-8",
    )
    summarizer = Summarizer()
    messages = summarizer._parse_transcript(path)
    assert len(messages) == 2


# ---------------------------------------------------------------------------
# _try_claude_cli
# ---------------------------------------------------------------------------

def test_try_claude_cli_timeout() -> None:
    summarizer = Summarizer()
    with patch("task_pilot.summarizer.subprocess.run", side_effect=TimeoutError):
        result = summarizer._try_claude_cli("test prompt")
    assert result is None


def test_try_claude_cli_not_found() -> None:
    summarizer = Summarizer()
    with patch("task_pilot.summarizer.subprocess.run", side_effect=FileNotFoundError):
        result = summarizer._try_claude_cli("test prompt")
    assert result is None
