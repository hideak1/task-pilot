"""Get the current git branch for a directory, or None."""

from __future__ import annotations

import subprocess


def current_branch(cwd: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=2,
        )
        if result.returncode != 0 or not result.stdout.strip() or result.stdout.strip() == "HEAD":
            # Fallback for unborn branches (freshly init'd repos with no commits)
            result = subprocess.run(
                ["git", "-C", cwd, "symbolic-ref", "--short", "HEAD"],
                capture_output=True, text=True, timeout=2,
            )
            if result.returncode != 0:
                return None
        branch = result.stdout.strip()
        return branch if branch and branch != "HEAD" else None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
