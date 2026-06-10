"""weekly.py — Sunday weekly reflection (separate small Ollama call)."""
from __future__ import annotations

import datetime as dt
import json
import urllib.error
import urllib.request

from config import DEFAULT_MODEL, OLLAMA_MAX_RETRIES, OLLAMA_NUM_CTX, OLLAMA_URL
from note_io import JOURNAL_HEADING, WINS_HEADING, note_path_for
from rules import slipped_tasks
from vault import RECURRING_TASKS, extract_section, parse_tasks, read_note

WEEKLY_HEADING = "🗓 Weekly Reflection"

WEEKLY_PROMPT = """You are a warm, perceptive weekly-reflection coach reviewing one week of the user's daily notes.

Output STRICT JSON ONLY:
{"patterns": [2-4 strings], "wins": [2-4 strings],
 "slipped": [0-3 strings], "one_change": string}

Rules:
- patterns: emotional/behavioral threads across the week, grounded in what the user actually wrote ("energy dipped midweek after the late nights"). Specific, not horoscopes.
- wins: real wins from the week worth celebrating, in the user's terms.
- slipped: what repeatedly didn't happen, stated plainly but kindly.
- one_change: ONE small, concrete experiment for next week — a single sentence, doable, tied to a pattern above.
- Speak to the user as "you". No names of other people. JSON only."""

_MAX_JOURNAL_CHARS = 400


def build_week_digest(today: dt.date) -> str:
    """Last 7 days of notes (completed/open tasks, wins, journal excerpts)."""
    chunks: list[str] = []
    for i in range(6, -1, -1):
        d = today - dt.timedelta(days=i)
        path = note_path_for(d)
        if not path.exists():
            continue
        text = read_note(path)
        done, not_done = parse_tasks(text)
        completed = [t for t in done if t.strip() not in RECURRING_TASKS]
        still_open = [t for t in not_done if t.strip() not in RECURRING_TASKS]
        journal = extract_section(text, JOURNAL_HEADING).strip()[:_MAX_JOURNAL_CHARS]
        wins = extract_section(text, WINS_HEADING).strip()[:_MAX_JOURNAL_CHARS]
        chunks.append(
            f"### {d.strftime('%A %b %d')}\n"
            f"Completed: {', '.join(completed) or '(none)'}\n"
            f"Still open: {', '.join(still_open) or '(none)'}\n"
            f"Wins: {wins or '(empty)'}\n"
            f"Journal: {journal or '(empty)'}"
        )
    slipped = slipped_tasks(today)
    if slipped:
        chunks.append(
            "### Carried over all week\n"
            + "\n".join(f"- {t} ({n} days)" for t, n in slipped[:5])
        )
    return "\n\n".join(chunks)


def ask_weekly(
    digest: str, model: str = DEFAULT_MODEL, ollama_url: str = OLLAMA_URL
) -> dict:
    payload = {
        "model": model,
        "system": WEEKLY_PROMPT,
        "prompt": f"This week's notes:\n\n{digest}\n\nNow produce the JSON object.",
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.4, "num_ctx": OLLAMA_NUM_CTX},
    }
    last_err: Exception | None = None
    for _attempt in range(OLLAMA_MAX_RETRIES):
        try:
            req = urllib.request.Request(
                ollama_url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=180) as resp:
                body = json.loads(resp.read())
            data = json.loads(body.get("response", "").strip())
            if isinstance(data, dict) and data.get("one_change"):
                return data
        except (urllib.error.URLError, json.JSONDecodeError, OSError) as e:
            last_err = e
    raise RuntimeError(f"weekly reflection call failed: {last_err}")


def render_weekly(plan: dict) -> str:
    def _items(key: str) -> list[str]:
        v = plan.get(key, [])
        return [str(x).strip() for x in v if str(x).strip()] if isinstance(v, list) else []

    parts: list[str] = []
    if _items("patterns"):
        parts.append("**Patterns**\n" + "\n".join(f"- {x}" for x in _items("patterns")))
    if _items("wins"):
        parts.append("**Wins**\n" + "\n".join(f"- {x}" for x in _items("wins")))
    if _items("slipped"):
        parts.append(
            "**What kept slipping**\n" + "\n".join(f"- {x}" for x in _items("slipped"))
        )
    change = str(plan.get("one_change", "")).strip()
    if change:
        parts.append(f"**One change for next week**\n- {change}")
    return "\n\n".join(parts) or "(no reflection generated)"
