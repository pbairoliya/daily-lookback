"""note_io.py — Obsidian daily note read/write helpers (no AI)."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from config import DAILY_DIR, TEMPLATE_PATH
from taskkeys import bill_key, is_payment_task, task_key
from vault import extract_section

FOCUS_HEADING = "🎯 Today's Focus"
TASKS_HEADING = "✅ Tasks"
AIJOURNEY_HEADING = "🤖 AI Journey"
LEARNINGS_HEADING = "🧠 Learnings"
BLOG_HEADING = "✍️ Blog Ideas / Drafts"
WINS_HEADING = "🏆 Wins & Gratitude"
JOURNAL_HEADING = "📓 Journal"
TOMORROW_HEADING = "🔜 Tomorrow"
LOOKBACK_HEADING = "🪞 Looking back"
REMINDERS_HEADING = "🔔 Reminders"


def note_path_for(date: dt.date) -> Path:
    return DAILY_DIR / f"{date.isoformat()}.md"


def render_template(date: dt.date) -> str:
    text = TEMPLATE_PATH.read_text(encoding="utf-8")
    long_form = f"{date.strftime('%A, %B')} {date.day}, {date.year}"
    text = text.replace("{{date:YYYY-MM-DD}}", date.isoformat())
    text = text.replace("{{date:dddd, MMMM D, YYYY}}", long_form)
    return text


def _section_bounds(lines: list[str], heading: str) -> tuple[int, int] | None:
    header = f"## {heading}"
    for i, line in enumerate(lines):
        if line.startswith(header):
            end = len(lines)
            for j in range(i + 1, len(lines)):
                if lines[j].startswith("## "):
                    end = j
                    break
            return i, end
    return None


def inject_section(note_text: str, heading: str, section_body: str) -> str:
    lines = note_text.split("\n")
    header_line = f"## {heading}"
    new_block = [header_line, "", section_body.strip(), ""]

    bounds = _section_bounds(lines, heading)
    if bounds is not None:
        start, end = bounds
        return "\n".join(lines[:start] + new_block + lines[end:])

    for i, line in enumerate(lines):
        if line.startswith("# ") and not line.startswith("## "):
            return "\n".join(lines[: i + 1] + [""] + new_block + lines[i + 1 :])

    return note_text.rstrip() + "\n\n" + "\n".join(new_block)


def is_section_empty(note_text: str, heading: str) -> bool:
    body = extract_section(note_text, heading)
    for line in body.split("\n"):
        s = line.strip()
        if not s or s.startswith(">") or s in ("-", "- "):
            continue
        return False
    return True


def replace_section_body(note_text: str, heading: str, new_body_lines: list[str]) -> str:
    if not new_body_lines:
        return note_text
    lines = note_text.split("\n")
    bounds = _section_bounds(lines, heading)
    if bounds is None:
        return note_text
    start, end = bounds

    hints: list[str] = []
    i = start + 1
    while i < end:
        s = lines[i].strip()
        if s.startswith(">"):
            hints.append(lines[i])
            i += 1
        elif not s and not hints:
            i += 1
        else:
            break

    replacement = [lines[start]] + hints + list(new_body_lines) + [""]
    return "\n".join(lines[:start] + replacement + lines[end:])


def fill_if_empty(note_text: str, heading: str, items: list[str]) -> str:
    if not items or not is_section_empty(note_text, heading):
        return note_text
    return replace_section_body(note_text, heading, [f"- {x}" for x in items])


def is_prompt_only_section(note_text: str, heading: str) -> bool:
    """True if the section is empty or only contains prior coach prompt bullets."""
    body = extract_section(note_text, heading)
    content_lines: list[str] = []
    for line in body.split("\n"):
        s = line.strip()
        if not s or s.startswith(">"):
            continue
        content_lines.append(s)
    if not content_lines:
        return True
    return all(
        s.startswith("- ") and s.removeprefix("- ").strip().endswith("?")
        for s in content_lines
    )


def refresh_prompts(note_text: str, heading: str, items: list[str]) -> str:
    """Replace coach prompts when empty or still only questions; keep real journal prose."""
    if not items:
        return note_text
    if is_section_empty(note_text, heading) or is_prompt_only_section(note_text, heading):
        return replace_section_body(note_text, heading, [f"- {x}" for x in items])
    return note_text


def existing_task_texts(note_text: str) -> set[str]:
    """All task strings under ## Tasks (checked or unchecked)."""
    body = extract_section(note_text, TASKS_HEADING)
    found: set[str] = set()
    for line in body.split("\n"):
        s = line.strip()
        if s.startswith("- [ ]"):
            found.add(s.removeprefix("- [ ]").strip())
        elif s.startswith("- [x]"):
            found.add(s.removeprefix("- [x]").strip())
    return found


def tasks_missing_from_note(note_text: str, tasks: list[str]) -> list[str]:
    """REQUIRED/smart tasks not yet present in the Tasks section (by key)."""
    existing = {task_key(t) for t in existing_task_texts(note_text)}
    out: list[str] = []
    for t in tasks:
        t = (t or "").strip()
        k = task_key(t) if t else ""
        if t and k and k not in existing:
            existing.add(k)
            out.append(t)
    return out


def is_tasks_pristine(note_text: str) -> bool:
    body = extract_section(note_text, TASKS_HEADING)
    for line in body.split("\n"):
        s = line.strip()
        if s.startswith("**") and s.endswith("**") and len(s) >= 4:
            return False
    return True


_is_payment_task = is_payment_task


# Category-label brackets that only appear on Reminders/inbox lines. If the model
# copies one of these into a task, it's echoing an email — drop it (inbox items
# live in ## 🔔 Reminders, not ## ✅ Tasks; only "Pay …" bills become tasks).
_REMINDER_ECHO_MARKERS = (
    "[bill due", "[money", "[venmo", "[decision]", "[fyi]", "[reply needed]",
    "[housing", "[review]", "[deadline]", "[statement",
)


def is_reminder_echo(item: str) -> bool:
    low = item.lower()
    return any(mk in low for mk in _REMINDER_ECHO_MARKERS) or '] — "' in item


def strip_reminder_echoes(note_text: str) -> str:
    """Remove copied email/reminder lines from ## Tasks, dropping now-empty buckets.

    Catches echoes that arrive via carry-over from a prior note's Tasks, not just
    the model's fresh output.
    """
    lines = note_text.split("\n")
    bounds = _section_bounds(lines, TASKS_HEADING)
    if bounds is None:
        return note_text
    start, end = bounds
    kept: list[str] = []
    header: str | None = None
    items: list[str] = []

    def flush() -> None:
        nonlocal header, items
        if items:
            if header is not None:
                kept.append(header)
            kept.extend(items)
            kept.append("")
        header, items = None, []

    for line in lines[start + 1 : end]:
        s = line.strip()
        if s.startswith("**") and s.endswith("**"):
            flush()
            header = line
        elif s.startswith("- [ ]") and is_reminder_echo(s.removeprefix("- [ ]").strip()):
            continue
        elif s:
            items.append(line)
    flush()
    return "\n".join(lines[: start + 1] + [""] + kept + lines[end:])


def extract_task_states(note_text: str) -> list[tuple[str, bool]]:
    """Every task line under ## Tasks as (text, checked) — preserves done state so
    a re-bucketing pass can keep completed tasks checked."""
    out: list[tuple[str, bool]] = []
    for line in extract_section(note_text, TASKS_HEADING).split("\n"):
        s = line.strip()
        if s.startswith("- [x]"):
            t = s.removeprefix("- [x]").strip()
            if t:
                out.append((t, True))
        elif s.startswith("- [ ]"):
            t = s.removeprefix("- [ ]").strip()
            if t:
                out.append((t, False))
    return out


def render_task_groups(groups: list[dict], required: list[str]) -> list[str]:
    """Deterministically bucketed Tasks body from the coach's suggested items.

    The coach's bucket NAMES are ignored — only its task content is used; every
    task is re-categorized by taskcat into a fixed, stable taxonomy.
    """
    import taskcat

    tasks: list[tuple[str, bool]] = []
    for g in groups or []:
        if not isinstance(g, dict):
            continue
        raw_items = g.get("items", [])
        if not isinstance(raw_items, list):
            continue
        for it in raw_items:
            tasks.append((str(it), False))
    return taskcat.render_grouped(tasks, required)


def append_tasks(note_text: str, tasks: list[str]) -> str:
    if not tasks:
        return note_text
    lines = note_text.split("\n")
    bounds = _section_bounds(lines, TASKS_HEADING)
    if bounds is None:
        return note_text
    start, end = bounds

    existing: set[str] = set()
    for line in lines[start + 1 : end]:
        s = line.strip()
        if s.startswith("- [ ]"):
            existing.add(task_key(s.removeprefix("- [ ]").strip()))
        elif s.startswith("- [x]"):
            existing.add(task_key(s.removeprefix("- [x]").strip()))

    fresh: list[str] = []
    for t in tasks:
        t = (t or "").strip()
        k = task_key(t) if t else ""
        if t and k and k not in existing:
            existing.add(k)
            fresh.append(t)
    if not fresh:
        return note_text

    insert_at = end
    while insert_at > start + 1 and lines[insert_at - 1].strip() == "":
        insert_at -= 1
    new_lines = [f"- [ ] {t}" for t in fresh]
    return "\n".join(lines[:insert_at] + new_lines + lines[insert_at:])


def upsert_tasks(note_text: str, tasks: list[str]) -> str:
    """Insert or refresh tasks (used for bills) in ## Tasks.

    Per task: an existing line with the same task_key means it's already
    there → skip. An UNCHECKED line with the same bill_key but different
    text is the same bill with a stale amount/due date → rewrite that line
    in place (bucket/position preserved). A CHECKED line with the same
    bill_key means it's already paid → skip. Otherwise append.
    """
    if not tasks:
        return note_text
    lines = note_text.split("\n")
    bounds = _section_bounds(lines, TASKS_HEADING)
    if bounds is None:
        return note_text
    start, end = bounds

    to_append: list[str] = []
    handled: set[str] = set()  # identities already processed this call
    for t in (x.strip() for x in tasks if x):
        if not t:
            continue
        tk = task_key(t)
        bk = bill_key(t) or tk
        if not tk or bk in handled:
            continue
        handled.add(bk)

        found = False
        for i in range(start + 1, end):
            s = lines[i].strip()
            unchecked = s.startswith("- [ ]")
            checked = s.startswith("- [x]")
            if not (unchecked or checked):
                continue
            existing = s.removeprefix("- [ ]").removeprefix("- [x]").strip()
            ek = task_key(existing)
            if ek == tk or (bill_key(existing) or ek) == bk:
                if unchecked and existing != t:
                    indent = lines[i][: len(lines[i]) - len(lines[i].lstrip())]
                    lines[i] = f"{indent}- [ ] {t}"
                found = True
                break
        if not found:
            to_append.append(t)

    text = "\n".join(lines)
    return append_tasks(text, to_append) if to_append else text


def strip_unchecked_tasks(note_text: str, patterns: list[str]) -> str:
    from rules import matches_word

    lines = note_text.split("\n")
    bounds = _section_bounds(lines, TASKS_HEADING)
    if bounds is None:
        return note_text
    start, end = bounds
    out: list[str] = []
    for i, line in enumerate(lines):
        if start < i < end and line.strip().startswith("- [ ]"):
            task = line.strip().removeprefix("- [ ]").strip()
            if matches_word(task, patterns):
                continue
        out.append(line)
    return "\n".join(out)


def strip_unchecked_where(note_text: str, predicate) -> str:
    """Remove unchecked Tasks lines where `predicate(task_text)` is True.

    Predicate-based sibling of strip_unchecked_in_set, so a caller can supply
    arbitrary logic (e.g. 'this bill is already paid this cycle') without this
    module importing rules. Checked ([x]) lines are always left alone.
    """
    lines = note_text.split("\n")
    bounds = _section_bounds(lines, TASKS_HEADING)
    if bounds is None:
        return note_text
    start, end = bounds
    out: list[str] = []
    for i, line in enumerate(lines):
        if start < i < end and line.strip().startswith("- [ ]"):
            task = line.strip().removeprefix("- [ ]").strip()
            if predicate(task):
                continue
        out.append(line)
    return "\n".join(out)


def strip_unchecked_in_set(note_text: str, normalized: set[str]) -> str:
    """Remove unchecked tasks whose normalized text is in `normalized`.

    Used to pull out tasks already completed within the grace period, so a
    recently-done one-off (e.g. 'Record Influenster video') can't reappear.
    """
    if not normalized:
        return note_text
    from rules import normalize_task

    lines = note_text.split("\n")
    bounds = _section_bounds(lines, TASKS_HEADING)
    if bounds is None:
        return note_text
    start, end = bounds
    out: list[str] = []
    for i, line in enumerate(lines):
        if start < i < end and line.strip().startswith("- [ ]"):
            task = line.strip().removeprefix("- [ ]").strip()
            if normalize_task(task) in normalized:
                continue
        out.append(line)
    return "\n".join(out)
