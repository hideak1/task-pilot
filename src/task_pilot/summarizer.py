"""Summary generator for Claude Code session transcripts.

Strategy:
- Historical sessions: first user message truncated to ~60 chars (zero cost)
- Active/new sessions: try Codex MCP for real summary, fallback to first message
"""

from __future__ import annotations

import json
import re
from pathlib import Path


class Summarizer:
    """Generate titles and summaries from session transcripts."""

    ACTION_PATTERNS = [
        re.compile(r"^\s*\d+\.\s+(.+)", re.MULTILINE),
        re.compile(
            r"(?:you need to|please run|you should|you must|you can|make sure to)\s+(.+)",
            re.IGNORECASE,
        ),
    ]

    COMMAND_KEYWORDS = ("scp", "ssh", "copy", "upload", "download", "rsync", "curl", "wget")

    # ── Title (cheap, always local) ──────────────────────────────

    def title_from_transcript(self, path: Path) -> str:
        """Extract a short title from the first user message. Pure local, zero cost."""
        messages = self._parse_transcript(path)
        for msg in messages:
            if msg.get("type") not in ("user", "human"):
                continue
            text = self._get_text_content(msg)
            if text:
                return self._clean_title(text)
        return "Untitled"

    @staticmethod
    def _clean_title(raw: str) -> str:
        text = re.sub(r"<[^>]+>", "", raw).strip()
        # Take first non-empty line
        for line in text.splitlines():
            line = line.strip()
            if line:
                text = line
                break
        if len(text) > 60:
            text = text[:57] + "..."
        return text

    # ── Summary (tries AI, falls back to local) ─────────────────

    def summarize(self, path: Path, use_ai: bool = True) -> str | None:
        """Generate a summary.

        If use_ai=True, tries Codex first, then falls back to heuristic.
        If use_ai=False, uses heuristic only.
        """
        messages = self._parse_transcript(path)
        if not messages:
            return None

        if use_ai:
            ai_summary = self._try_codex(messages)
            if ai_summary:
                return ai_summary

        return self._heuristic_summary(messages)

    def _try_codex(self, messages: list[dict]) -> str | None:
        """Try to use Codex MCP for summarization. Returns None on failure."""
        # This is called externally by the hook/scanner layer which has
        # access to the MCP runtime. We provide the prompt builder here,
        # but the actual MCP call must be done by the caller.
        # So this returns None — the caller should use build_summary_prompt()
        # and call codex themselves.
        return None

    def build_summary_prompt(self, path: Path) -> str | None:
        """Build a prompt suitable for Codex/AI summarization.

        Returns a prompt string, or None if transcript is empty.
        Sends only the first 3 and last 3 user/assistant messages
        to keep token cost low.
        """
        messages = self._parse_transcript(path)
        if not messages:
            return None

        # Filter to user/assistant only
        conversations = [
            m for m in messages
            if m.get("type") in ("user", "human", "assistant")
        ]
        if not conversations:
            return None

        # Take first 3 + last 3 (deduplicated)
        if len(conversations) <= 6:
            sample = conversations
        else:
            sample = conversations[:3] + conversations[-3:]

        parts = []
        for msg in sample:
            role = "User" if msg.get("type") in ("user", "human") else "Assistant"
            text = self._get_text_content(msg)
            if text:
                # Truncate individual messages
                if len(text) > 300:
                    text = text[:297] + "..."
                parts.append(f"{role}: {text}")

        transcript_text = "\n\n".join(parts)
        return (
            "Summarize this Claude Code session in 1-2 sentences. "
            "Focus on WHAT was accomplished, not HOW.\n\n"
            f"{transcript_text}"
        )

    def _heuristic_summary(self, messages: list[dict]) -> str:
        """Fallback: first user message as title."""
        for msg in messages:
            if msg.get("type") not in ("user", "human"):
                continue
            text = self._get_text_content(msg)
            if text:
                return self._clean_title(text)
        return ""

    # ── Action Items ─────────────────────────────────────────────

    def extract_action_items(self, path: Path) -> list[str]:
        """Find human action items from the transcript."""
        messages = self._parse_transcript(path)
        items: list[str] = []

        for msg in messages:
            if msg.get("type") != "assistant":
                continue
            content = self._get_text_content(msg)
            if not content:
                continue

            for pattern in self.ACTION_PATTERNS:
                for match in pattern.finditer(content):
                    item = match.group(1).strip()
                    if item and item not in items:
                        items.append(item)

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

    # ── Helpers ───────────────────────────────────────────────────

    @staticmethod
    def _get_text_content(msg: dict) -> str:
        """Extract text from a message, handling string and list-of-blocks."""
        message = msg.get("message", {})
        content = message.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            text_parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
                elif isinstance(block, str):
                    text_parts.append(block)
            return "\n".join(text_parts)
        return ""

    def _parse_transcript(self, path: Path) -> list[dict]:
        """Parse .jsonl transcript file into list of message dicts."""
        if not path.exists():
            return []

        messages: list[dict] = []
        try:
            text = path.read_text(encoding="utf-8").strip()
        except OSError:
            return []
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
