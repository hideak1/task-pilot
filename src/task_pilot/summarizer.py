"""Summary generator for Claude Code session transcripts.

Strategy:
- Title: try codex exec → fallback to first user message (~60 chars)
- Summary: try codex exec → fallback to first user message
- Codex is safe: separate OpenAI process, no Claude Code hooks triggered
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

CODEX_TIMEOUT = 30  # seconds


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

    # ── Title ────────────────────────────────────────────────────

    def generate_title(self, path: Path, use_ai: bool = True) -> str:
        """Generate a short title for a session.

        Tries codex exec first, falls back to first user message.
        """
        messages = self._parse_transcript(path)
        if not messages:
            return "Untitled"

        if use_ai:
            snippet = self._build_snippet(messages)
            ai_title = self._run_codex(
                f"Generate a short title (under 50 chars, no quotes) for this coding session:\n\n{snippet}"
            )
            if ai_title:
                # Clean up: strip quotes, truncate
                ai_title = ai_title.strip().strip('"').strip("'")
                if len(ai_title) > 60:
                    ai_title = ai_title[:57] + "..."
                return ai_title

        # Fallback: first user message
        return self._title_from_first_message(messages)

    def title_from_transcript(self, path: Path) -> str:
        """Local-only title extraction (zero cost). Used for historical sessions."""
        messages = self._parse_transcript(path)
        return self._title_from_first_message(messages)

    def _title_from_first_message(self, messages: list[dict]) -> str:
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
        for line in text.splitlines():
            line = line.strip()
            if line:
                text = line
                break
        if len(text) > 60:
            text = text[:57] + "..."
        return text

    # ── Summary ──────────────────────────────────────────────────

    def summarize(self, path: Path, use_ai: bool = True) -> str | None:
        """Generate a summary.

        Tries codex exec first, falls back to first user message.
        """
        messages = self._parse_transcript(path)
        if not messages:
            return None

        if use_ai:
            snippet = self._build_snippet(messages)
            ai_summary = self._run_codex(
                f"Summarize this Claude Code session in 1-2 sentences. "
                f"Focus on WHAT was accomplished.\n\n{snippet}"
            )
            if ai_summary:
                return ai_summary

        # Fallback
        return self._title_from_first_message(messages)

    # ── Codex CLI ────────────────────────────────────────────────

    @staticmethod
    def _run_codex(prompt: str) -> str | None:
        """Run codex exec in read-only sandbox. Returns output or None."""
        if not shutil.which("codex"):
            return None
        try:
            result = subprocess.run(
                ["codex", "exec", "--sandbox", "read-only", prompt],
                capture_output=True,
                text=True,
                timeout=CODEX_TIMEOUT,
            )
            output = result.stdout.strip()
            if result.returncode == 0 and output:
                return output
        except (subprocess.TimeoutExpired, OSError) as e:
            logger.debug(f"Codex exec failed: {e}")
        return None

    def _build_snippet(self, messages: list[dict]) -> str:
        """Build a short transcript snippet for AI (first 3 + last 3 messages)."""
        conversations = [
            m for m in messages
            if m.get("type") in ("user", "human", "assistant")
        ]
        if not conversations:
            return ""

        if len(conversations) <= 6:
            sample = conversations
        else:
            sample = conversations[:3] + conversations[-3:]

        parts = []
        for msg in sample:
            role = "User" if msg.get("type") in ("user", "human") else "Assistant"
            text = self._get_text_content(msg)
            if text:
                if len(text) > 300:
                    text = text[:297] + "..."
                parts.append(f"{role}: {text}")

        return "\n\n".join(parts)

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
