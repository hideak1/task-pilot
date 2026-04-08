"""Clean a raw user message into a short title."""

import re


def clean_title(raw: str) -> str:
    text = re.sub(r"<[^>]+>", "", raw).strip()
    for line in text.splitlines():
        line = line.strip()
        if line:
            text = line
            break
    if len(text) > 60:
        text = text[:57] + "..."
    return text
