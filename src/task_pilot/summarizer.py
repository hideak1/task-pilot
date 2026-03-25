"""Summary generator for Claude Code session transcripts."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path


class Summarizer:
    """Generate summaries and extract action items from session transcripts."""

    CLAUDE_TIMEOUT = 30  # seconds

    ACTION_PATTERNS = [
        re.compile(r"^\s*\d+\.\s+(.+)", re.MULTILINE),  # numbered lists
        re.compile(
            r"(?:you need to|please run|you should|you must|you can|make sure to)\s+(.+)",
            re.IGNORECASE,
        ),
    ]

    COMMAND_KEYWORDS = ("scp", "ssh", "copy", "upload", "download", "rsync", "curl", "wget")

    def from_transcript(self, path: Path, use_cli: bool = False) -> str | None:
        """Generate summary from transcript.

        Args:
            path: Path to .jsonl transcript file.
            use_cli: If True, try claude CLI first (CAUTION: this spawns a
                     Claude session which can trigger hooks — only use when
                     explicitly requested, never in automated scan loops).
        """
        messages = self._parse_transcript(path)
        if not messages:
            return None

        if use_cli:
            prompt = self._build_prompt(messages)
            summary = self._try_claude_cli(prompt)
            if summary:
                return summary

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
                        # Avoid duplicates from numbered-list extraction
                        already = any(line_stripped.endswith(existing) or existing.endswith(line_stripped) for existing in items)
                        if not already:
                            items.append(line_stripped)
                        break

        return items

    def _try_claude_cli(self, prompt: str) -> str | None:
        """Run echo prompt | claude --print, return output or None."""
        try:
            result = subprocess.run(
                ["claude", "--print"],
                input=prompt,
                capture_output=True,
                text=True,
                timeout=self.CLAUDE_TIMEOUT,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass
        return None

    def _heuristic_summary(self, messages: list[dict]) -> str:
        """First user message as title context, last assistant as summary."""
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
            # Truncate long user messages to use as a title line
            title = first_user if len(first_user) <= 120 else first_user[:117] + "..."
            parts.append(f"Task: {title}")
        if last_assistant:
            # Truncate long assistant messages
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

    def _build_prompt(self, messages: list[dict]) -> str:
        """Build a summarization prompt from parsed messages."""
        parts = ["Summarize this Claude Code session in 2-3 sentences:\n"]
        for msg in messages:
            role = msg.get("type", "unknown")
            content = msg.get("message", {}).get("content", "")
            if role in ("user", "assistant") and content:
                parts.append(f"[{role}]: {content[:300]}")
        return "\n".join(parts)
