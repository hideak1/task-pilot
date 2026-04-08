import json
from pathlib import Path
from task_pilot.transcript_reader import (
    sum_tokens,
    last_activity_timestamp,
    extract_first_user_message,
)


def make_jsonl(tmp_path: Path, entries: list[dict]) -> Path:
    path = tmp_path / "session.jsonl"
    with path.open("w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")
    return path


def test_sum_tokens_basic(tmp_path):
    path = make_jsonl(tmp_path, [
        {"type": "user", "message": {"content": "hi"}},
        {"type": "assistant", "message": {
            "usage": {"input_tokens": 10, "output_tokens": 20,
                       "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        }},
        {"type": "assistant", "message": {
            "usage": {"input_tokens": 5, "output_tokens": 7,
                       "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        }},
    ])
    assert sum_tokens(path) == 10 + 20 + 5 + 7


def test_sum_tokens_handles_missing_usage(tmp_path):
    path = make_jsonl(tmp_path, [
        {"type": "assistant", "message": {"content": "no usage field"}},
    ])
    assert sum_tokens(path) == 0


def test_sum_tokens_returns_zero_for_missing_file(tmp_path):
    assert sum_tokens(tmp_path / "missing.jsonl") == 0


def test_last_activity_timestamp(tmp_path):
    path = make_jsonl(tmp_path, [
        {"type": "user", "timestamp": "2026-04-08T12:00:00Z"},
        {"type": "assistant", "timestamp": "2026-04-08T12:01:00Z"},
    ])
    ts = last_activity_timestamp(path)
    assert ts > 0


def test_last_activity_timestamp_falls_back_to_file_mtime(tmp_path):
    path = make_jsonl(tmp_path, [
        {"type": "user"},  # no timestamp field
    ])
    ts = last_activity_timestamp(path)
    assert ts > 0  # uses mtime


def test_extract_first_user_message(tmp_path):
    path = make_jsonl(tmp_path, [
        {"type": "user", "message": {"content": "Build a REST API"}},
        {"type": "assistant", "message": {"content": "OK"}},
    ])
    assert extract_first_user_message(path) == "Build a REST API"


def test_extract_first_user_message_handles_list_content(tmp_path):
    path = make_jsonl(tmp_path, [
        {"type": "user", "message": {"content": [{"type": "text", "text": "hi there"}]}},
    ])
    assert extract_first_user_message(path) == "hi there"


def test_extract_first_user_message_returns_none_when_no_user(tmp_path):
    path = make_jsonl(tmp_path, [
        {"type": "assistant", "message": {"content": "hi"}},
    ])
    assert extract_first_user_message(path) is None
