"""Tests for the Summarizer class."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from task_pilot.summarizer import Summarizer


def make_transcript(tmp_path: Path, entries: list[dict]) -> Path:
    path = tmp_path / "transcript.jsonl"
    lines = [json.dumps(e) for e in entries]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


# ── title_from_transcript ────────────────────────────────────

def test_title_basic(tmp_path: Path) -> None:
    path = make_transcript(tmp_path, [
        {"type": "user", "message": {"content": "Build a REST API"}},
        {"type": "assistant", "message": {"content": "Sure!"}},
    ])
    s = Summarizer()
    assert s.title_from_transcript(path) == "Build a REST API"


def test_title_strips_xml_tags(tmp_path: Path) -> None:
    path = make_transcript(tmp_path, [
        {"type": "user", "message": {"content": "<command-name>commit</command-name>fix the bug"}},
    ])
    s = Summarizer()
    assert "command-name" not in s.title_from_transcript(path)
    assert "fix the bug" in s.title_from_transcript(path)


def test_title_truncates_to_60(tmp_path: Path) -> None:
    path = make_transcript(tmp_path, [
        {"type": "user", "message": {"content": "A" * 200}},
    ])
    s = Summarizer()
    title = s.title_from_transcript(path)
    assert len(title) == 60
    assert title.endswith("...")


def test_title_empty_transcript(tmp_path: Path) -> None:
    path = tmp_path / "empty.jsonl"
    path.write_text("")
    s = Summarizer()
    assert s.title_from_transcript(path) == "Untitled"


def test_title_handles_content_list(tmp_path: Path) -> None:
    path = make_transcript(tmp_path, [
        {"type": "human", "message": {"content": [
            {"type": "text", "text": "Implement login flow"},
        ]}},
    ])
    s = Summarizer()
    assert s.title_from_transcript(path) == "Implement login flow"


# ── summarize ────────────────────────────────────────────────

def test_summarize_heuristic(tmp_path: Path) -> None:
    path = make_transcript(tmp_path, [
        {"type": "user", "message": {"content": "Build a REST API for user management"}},
        {"type": "assistant", "message": {"content": "Done!"}},
    ])
    s = Summarizer()
    summary = s.summarize(path, use_ai=False)
    assert summary is not None
    assert "REST API" in summary


def test_summarize_empty(tmp_path: Path) -> None:
    path = tmp_path / "empty.jsonl"
    path.write_text("")
    s = Summarizer()
    assert s.summarize(path) is None


def test_summarize_missing_file(tmp_path: Path) -> None:
    s = Summarizer()
    assert s.summarize(tmp_path / "nope.jsonl") is None


# ── build_summary_prompt ─────────────────────────────────────

def test_build_summary_prompt(tmp_path: Path) -> None:
    path = make_transcript(tmp_path, [
        {"type": "user", "message": {"content": "Fix the login bug"}},
        {"type": "assistant", "message": {"content": "I found the issue in auth.py"}},
        {"type": "user", "message": {"content": "Great, deploy it"}},
        {"type": "assistant", "message": {"content": "Deployed to staging"}},
    ])
    s = Summarizer()
    prompt = s.build_summary_prompt(path)
    assert prompt is not None
    assert "login bug" in prompt
    assert "1-2 sentences" in prompt


def test_build_summary_prompt_limits_messages(tmp_path: Path) -> None:
    """Should take first 3 + last 3 messages."""
    entries = []
    for i in range(20):
        entries.append({"type": "user", "message": {"content": f"Message {i}"}})
        entries.append({"type": "assistant", "message": {"content": f"Reply {i}"}})
    path = make_transcript(tmp_path, entries)
    s = Summarizer()
    prompt = s.build_summary_prompt(path)
    assert "Message 0" in prompt   # first
    assert "Reply 19" in prompt    # last
    assert "Message 10" not in prompt  # middle excluded


def test_build_summary_prompt_empty(tmp_path: Path) -> None:
    path = tmp_path / "empty.jsonl"
    path.write_text("")
    s = Summarizer()
    assert s.build_summary_prompt(path) is None


# ── extract_action_items ─────────────────────────────────────

def test_extract_action_items(tmp_path: Path) -> None:
    path = make_transcript(tmp_path, [
        {"type": "assistant", "message": {"content": (
            "You need to:\n1. scp train.py to GPU\n2. Run python train.py"
        )}},
    ])
    s = Summarizer()
    items = s.extract_action_items(path)
    assert len(items) >= 2


def test_extract_action_items_empty(tmp_path: Path) -> None:
    path = make_transcript(tmp_path, [
        {"type": "assistant", "message": {"content": "All done, nothing for you to do."}},
    ])
    s = Summarizer()
    assert s.extract_action_items(path) == []


def test_extract_action_items_please_run(tmp_path: Path) -> None:
    path = make_transcript(tmp_path, [
        {"type": "assistant", "message": {"content": "Please run `pytest` to verify."}},
    ])
    s = Summarizer()
    items = s.extract_action_items(path)
    assert any("pytest" in i for i in items)


# ── _parse_transcript edge cases ─────────────────────────────

def test_malformed_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text("not json\n{bad\n", encoding="utf-8")
    s = Summarizer()
    assert s.summarize(path) is None


def test_blank_lines_skipped(tmp_path: Path) -> None:
    path = tmp_path / "t.jsonl"
    path.write_text(
        '{"type":"user","message":{"content":"Hi"}}\n\n\n'
        '{"type":"assistant","message":{"content":"Hello"}}\n',
        encoding="utf-8",
    )
    s = Summarizer()
    msgs = s._parse_transcript(path)
    assert len(msgs) == 2
