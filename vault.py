"""
vault.py — pure-Python helpers for reading your Obsidian vault (no AI).
"""
from __future__ import annotations

from pathlib import Path

from config import DAILY_DIR  # noqa: F401 — re-export for `from vault import DAILY_DIR`

LEARNINGS_HEADING = "🧠 Learnings"

RECURRING_TASKS = {
    "Shower",
    "Work",
    "Study for 1 hour",
    "Workout",
    "Yoga",
    "Cook at least one meal",
    "🤖 AI learning (1–1.5h)",
    "🧮 Interview prep (LeetCode / system design)",
}


def recent_notes(n: int = 5) -> list[Path]:
    """Return the paths of the `n` most recent daily notes, newest first."""
    md_files = list(DAILY_DIR.glob("*.md"))
    return sorted(md_files, reverse=True)[:n]


def read_note(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def parse_tasks(text: str) -> tuple[list[str], list[str]]:
    done_tasks: list[str] = []
    not_done_tasks: list[str] = []
    for line in text.split("\n"):
        if line.startswith("- [x]"):
            done_tasks.append(line.removeprefix("- [x] "))
        elif line.startswith("- [ ]"):
            not_done_tasks.append(line.removeprefix("- [ ] "))
    return done_tasks, not_done_tasks


def extract_section(text: str, heading: str) -> str:
    lines = text.split("\n")
    start = None
    end = None
    for i, line in enumerate(lines):
        if start is None:
            if line.startswith("## " + heading):
                start = i + 1
        else:
            if line.startswith("## "):
                end = i
                break
    if start is None:
        return ""
    if end is None:
        end = len(lines)
    return "\n".join(lines[start:end])


def section_items(text: str, heading: str) -> list[str]:
    """Real bullet lines under a heading — hint (>) lines, blanks, and checkbox
    markers stripped. Used to read what the user actually wrote (e.g. yesterday's
    🔜 Tomorrow notes) as plain task-like strings."""
    out: list[str] = []
    for line in extract_section(text, heading).split("\n"):
        s = line.strip()
        if not s or s.startswith(">"):
            continue
        s = s.lstrip("-").strip()
        if s.startswith("[ ]") or s.startswith("[x]"):
            s = s[3:].strip()
        if s:
            out.append(s)
    return out
