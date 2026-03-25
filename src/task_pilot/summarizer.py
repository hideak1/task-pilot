"""Summary generator for Claude Code session transcripts.

Uses only local heuristics — no API calls, no subprocess, no token consumption.
"""

from __future__ import annotations

import json
import re
from pathlib import Path


class Summarizer:
    """Generate summaries and extract action items from session transcripts."""

    ACTION_PATTERNS = [
        re.compile(r"^\s*\d+\.\s+(.+)", re.MULTILINE),  # numbered lists
        re.compile(
            r"(?:you need to|please run|you should|you must|you can|make sure to)\s+(.+)",
            re.IGNORECASE,
        ),
    ]

    COMMAND_KEYWORDS = ("scp", "ssh", "copy", "upload", "download", "rsync", "curl", "wget")

    def from_transcript(self, path: Path) -> str | None:
        """Generate a heuristic summary from transcript (pure local, zero token cost)."""
        messages = self._parse_transcript(path)
        if not messages:
            return None
        return self._heuristic_summary(messages)

    def extract_action_items(self, path: Path) -> list[str]:
        """Find human action items from the transcript."""
        messages = self._parse_transcript(path)
        items: list[str] = []

        for msg in messages:
            if msg.get("type") != "assistant":
                continue
            content = msg.get("message", {}).get("content", "")
            if not content:
                continue

            # Check for numbered list items
            for pattern in self.ACTION_PATTERNS:
                for match in pattern.finditer(content):
                    item = match.group(1).strip()
                    if item and item not in items:
                        items.append(item)

            # Check for lines containing command keywords
            for line in content.splitlines():
                line_stripped = line.strip()
                if not line_stripped:
                    continue
                for kw in self.COMMAND_KEYWORDS:
                    if kw in line_stripped.lower() and line_stripped not in items:
                        already = any(
                            line_stripped.endswith(existing) or existing.endswith(line_stripped)
                            for existing in items
                        )
                        if not already:
                            items.append(line_stripped)
                        break

        return items

    def _heuristic_summary(self, messages: list[dict]) -> str:
        """First user message as task context, last assistant message as result."""
        first_user = ""
        last_assistant = ""

        for msg in messages:
            if msg.get("type") == "user" and not first_user:
                first_user = msg.get("message", {}).get("content", "")
            if msg.get("type") == "assistant":
                content = msg.get("message", {}).get("content", "")
                if content:
                    last_assistant = content

        parts: list[str] = []
        if first_user:
            title = first_user if len(first_user) <= 120 else first_user[:117] + "..."
            parts.append(f"Task: {title}")
        if last_assistant:
            body = last_assistant if len(last_assistant) <= 500 else last_assistant[:497] + "..."
            parts.append(f"Result: {body}")

        return "\n".join(parts) if parts else ""

    def _parse_transcript(self, path: Path) -> list[dict]:
        """Parse .jsonl transcript file into list of message dicts."""
        if not path.exists():
            return []

        messages: list[dict] = []
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            return []

        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                messages.append(obj)
            except json.JSONDecodeError:
                continue

        return messages
