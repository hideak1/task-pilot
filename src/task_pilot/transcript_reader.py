"""Read Claude Code transcript .jsonl files for tokens, activity, and titles."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path


def _iter_records(path: Path):
    """Yield parsed JSON records from a .jsonl file. Skip malformed lines."""
    if not path.exists():
        return
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    except OSError:
        return


def sum_tokens(path: Path) -> int:
    """Sum input + output + cache tokens across all assistant messages.

    Note: this approximates Claude's billing — exact counts depend on the
    Anthropic API's accounting which we cannot reproduce without recomputation.
    """
    total = 0
    for record in _iter_records(path):
        if record.get("type") != "assistant":
            continue
        message = record.get("message") or {}
        usage = message.get("usage") or {}
        total += usage.get("input_tokens", 0) or 0
        total += usage.get("output_tokens", 0) or 0
        total += usage.get("cache_creation_input_tokens", 0) or 0
        total += usage.get("cache_read_input_tokens", 0) or 0
    return total


def last_activity_timestamp(path: Path) -> float:
    """Return Unix timestamp of the last message, or file mtime as fallback."""
    last_ts = 0.0
    for record in _iter_records(path):
        ts_str = record.get("timestamp")
        if not ts_str:
            continue
        try:
            dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            last_ts = dt.timestamp()
        except (ValueError, TypeError):
            continue
    if last_ts > 0:
        return last_ts
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _get_text_content(message: dict) -> str:
    """Extract text from a message that may have string or list-of-blocks content."""
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                return block.get("text", "")
    return ""


def extract_first_user_message(path: Path) -> str | None:
    """Return the text of the first user message, or None if not found."""
    for record in _iter_records(path):
        if record.get("type") not in ("user", "human"):
            continue
        text = _get_text_content(record.get("message") or {})
        if text:
            return text
    return None
