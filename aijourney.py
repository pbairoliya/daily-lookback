"""aijourney.py — track the 16-week AI-engineer sprint in the daily note.

Deterministic, no LLM. Two jobs:

1. Read which days the "AI learning" checkbox was ticked in past notes and turn
   that into a streak (and a gentle nudge when it lapses). The coach must never
   *guess* whether you studied — you tick the box, this counts it.
2. Map today's date onto the sprint schedule (start date + 16 weeks) to surface
   the current phase, week number, and this week's deliverable.

Override the start date with AI_SPRINT_START=YYYY-MM-DD if you begin later than
the default Monday below.
"""
from __future__ import annotations

import datetime as dt
import os
import subprocess
from pathlib import Path

from vault import parse_tasks, read_note, recent_notes

# Monday of Week 1.
_DEFAULT_START = dt.date(2026, 6, 22)
TOTAL_WEEKS = 16

# Repos whose commits count as "AI work happened that day" — so the streak tracks
# real output, not just whether you remembered to tick the box. Overridable.
AI_REPOS_DIR = Path(os.environ.get("AI_REPOS_DIR", "~/ai-engineering")).expanduser()
_COMMIT_LOOKBACK_DAYS = 160

# Substrings (lowercased) that identify the recurring checkboxes. Substring —
# not exact — so a slightly reworded line still counts.
AI_LEARN_PATTERNS = ("ai learning",)
INTERVIEW_PATTERNS = ("interview prep",)
INTERVIEW_WEEKLY_TARGET = 3

# (first_week, last_week, phase name) — phases are four weeks each.
PHASES: list[tuple[int, int, str]] = [
    (1, 4, "Deep Learning & PyTorch fluency"),
    (5, 8, "Real RAG + Fine-tuning"),
    (9, 12, "MLOps & Cloud deployment"),
    (13, 16, "System Design & Interview execution"),
]

# week number -> this week's headline deliverable.
WEEK_PLAN: dict[int, str] = {
    1: "PyTorch tensors/autograd + image classifier (custom training loop)",
    2: "CNN from scratch; overfitting & regularization (fast.ai)",
    3: "Traditional ML review (sklearn) + a deployed Streamlit app",
    4: "Consolidate Phase 1: polish classifier repo + DL concept notes",
    5: "RAG fundamentals: chunking, embeddings, a real vector DB",
    6: "End-to-end RAG chatbot over PDFs with citations + eval (week2-rag)",
    7: "HF NLP course + Transformer internals; load Llama/Mistral",
    8: "Fine-tune (LoRA) on a small dataset (week3-agents)",
    9: "Wrap the RAG model in a documented FastAPI REST API",
    10: "Experiment tracking (W&B) + Dockerize the API",
    11: "Deploy to AWS + basic latency/cost monitoring",
    12: "Consolidate Phase 3: week4-capstone live URL + dashboard",
    13: "ML system design drills (recommendation, fraud, chatbot)",
    14: "Portfolio polish: 3 clean repos with READMEs + diagrams",
    15: "Pandas/comprehension drills + concept communication",
    16: "Mock interviews + final portfolio + build-in-public wrap",
}


def plan_start() -> dt.date:
    raw = os.environ.get("AI_SPRINT_START")
    if raw:
        try:
            return dt.date.fromisoformat(raw)
        except ValueError:
            pass
    return _DEFAULT_START


def _note_date(path: Path) -> dt.date | None:
    try:
        return dt.date.fromisoformat(path.stem)
    except ValueError:
        return None


def _notes_by_date(lookback_days: int) -> dict[dt.date, Path]:
    out: dict[dt.date, Path] = {}
    for note in recent_notes(lookback_days + 5):
        nd = _note_date(note)
        if nd is not None:
            out[nd] = note
    return out


def _did(text: str, patterns: tuple[str, ...]) -> bool:
    done, _ = parse_tasks(text)
    return any(p in d.lower() for d in done for p in patterns)


def learned_on(notes: dict[dt.date, Path], day: dt.date) -> bool:
    note = notes.get(day)
    return note is not None and _did(read_note(note), AI_LEARN_PATTERNS)


def _git(repo: Path, *args: str) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True, text=True, timeout=5,
        )
        return out.stdout if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def commit_dates(today: dt.date, lookback_days: int = _COMMIT_LOOKBACK_DAYS) -> set[dt.date]:
    """Dates (within the window) with at least one commit in any AI repo, so a day
    of real coding counts toward the streak even if the box went unticked."""
    out: set[dt.date] = set()
    if not AI_REPOS_DIR.exists():
        return out
    since = (today - dt.timedelta(days=lookback_days)).isoformat()
    for repo in sorted(AI_REPOS_DIR.iterdir()):
        if not (repo / ".git").exists():
            continue
        for line in _git(repo, "log", f"--since={since}", "--pretty=%cd", "--date=short").splitlines():
            try:
                out.add(dt.date.fromisoformat(line.strip()))
            except ValueError:
                continue
    return out


def commit_log(today: dt.date, days: int = 7, cap: int = 12) -> list[str]:
    """`repo: subject` for commits in the last `days` across AI repos, newest first.
    Feeds the weekly build-in-public draft."""
    rows: list[str] = []
    if not AI_REPOS_DIR.exists():
        return rows
    since = (today - dt.timedelta(days=days)).isoformat()
    for repo in sorted(AI_REPOS_DIR.iterdir()):
        if not (repo / ".git").exists():
            continue
        for subj in _git(repo, "log", f"--since={since}", "--no-merges", "--pretty=%s").splitlines():
            subj = subj.strip()
            if subj:
                rows.append(f"{repo.name}: {subj}")
    return rows[:cap]


def _did_ai(notes: dict[dt.date, Path], commits: set[dt.date], day: dt.date) -> bool:
    """A day counts if the AI-learning box was ticked OR you committed to an AI repo."""
    return learned_on(notes, day) or day in commits


def learning_streak(
    today: dt.date, lookback_days: int = 120, commits: set[dt.date] | None = None
) -> int:
    """Consecutive days up to and including yesterday that count (box OR commit).

    A missing/empty day ends the streak (no guessing across gaps). Today is
    excluded — the caller adds +1 when today already counts.
    """
    notes = _notes_by_date(lookback_days)
    if commits is None:
        commits = commit_dates(today)
    streak = 0
    for i in range(1, lookback_days + 1):
        if _did_ai(notes, commits, today - dt.timedelta(days=i)):
            streak += 1
        else:
            break
    return streak


def days_since_last_learn(
    today: dt.date, lookback_days: int = 60, commits: set[dt.date] | None = None
) -> int | None:
    """How many days ago AI work last happened (box OR commit); None if never."""
    notes = _notes_by_date(lookback_days)
    if commits is None:
        commits = commit_dates(today)
    for i in range(1, lookback_days + 1):
        if _did_ai(notes, commits, today - dt.timedelta(days=i)):
            return i
    return None


def interview_sessions_this_week(today: dt.date) -> int:
    """Days from Monday through today with the interview-prep box ticked."""
    notes = _notes_by_date(14)
    monday = today - dt.timedelta(days=today.weekday())
    count = 0
    day = monday
    while day <= today:
        note = notes.get(day)
        if note is not None and _did(read_note(note), INTERVIEW_PATTERNS):
            count += 1
        day += dt.timedelta(days=1)
    return count


def week_number(today: dt.date) -> int | None:
    """1-based sprint week, or None if today is before the start date."""
    start = plan_start()
    if today < start:
        return None
    return (today - start).days // 7 + 1


def phase_for(week: int) -> str:
    for lo, hi, name in PHASES:
        if lo <= week <= hi:
            return name
    return "Sprint complete"


def journey_lines(today: dt.date) -> list[str]:
    """Markdown bullets for the ## 🤖 AI Journey section."""
    notes = _notes_by_date(2)
    commits = commit_dates(today)
    today_done = _did_ai(notes, commits, today)
    today_via_commit = today in commits and not learned_on(notes, today)
    streak = learning_streak(today, commits=commits)
    lines: list[str] = []

    # 1) Streak / accountability line.
    if today_done:
        via = " (commit detected)" if today_via_commit else ""
        lines.append(f"- ✅ AI work logged today{via} — 🔥 {streak + 1}-day streak")
    elif streak:
        lines.append(
            f"- 🔥 {streak}-day streak — do today's 1–1.5h (or commit) to keep it alive"
        )
    else:
        last = days_since_last_learn(today, commits=commits)
        if last is not None:
            lines.append(
                f"- ⚠️ Last AI session was {last}d ago — do today's 1–1.5h to restart the streak"
            )
        else:
            lines.append("- ○ No streak yet — do today's 1–1.5h to start one")

    # 2) Interview-prep pace this week.
    n = interview_sessions_this_week(today)
    lines.append(f"- 🧮 Interview prep: {n}/{INTERVIEW_WEEKLY_TARGET} sessions this week")

    # 3) Where you are in the sprint.
    wk = week_number(today)
    start = plan_start()
    if wk is None:
        days = (start - today).days
        when = "tomorrow" if days == 1 else f"in {days}d"
        lines.append(f"- 🚀 Sprint starts {start:%a %b %d} ({when}) — Week 1: {WEEK_PLAN[1]}")
    elif wk > TOTAL_WEEKS:
        lines.append("- 🎉 16-week sprint complete — keep shipping & interviewing")
    else:
        lines.append(f"- 📅 Week {wk}/{TOTAL_WEEKS} · {phase_for(wk)}")
        lines.append(f"- 🎯 This week: {WEEK_PLAN.get(wk, '—')}")

    return lines


def focus_line(today: dt.date) -> str | None:
    """A single Focus bullet that pins today to the sprint's current deliverable,
    so the morning Focus always nudges the AI goal. None outside the sprint."""
    wk = week_number(today)
    if wk is None or wk > TOTAL_WEEKS:
        return None
    return f"🤖 Sprint Wk {wk}: {WEEK_PLAN.get(wk, '—')}"


def _active_days_this_week(today: dt.date) -> int:
    """Days from Monday→today with AI work (box or commit)."""
    notes = _notes_by_date(14)
    commits = commit_dates(today)
    monday = today - dt.timedelta(days=today.weekday())
    return sum(
        1
        for i in range((today - monday).days + 1)
        if _did_ai(notes, commits, monday + dt.timedelta(days=i))
    )


def weekly_progress(today: dt.date) -> str:
    """Sprint block appended to the Sunday Weekly Reflection."""
    wk = week_number(today)
    if wk is None:
        start = plan_start()
        return f"**🤖 AI sprint**\n- Starts {start:%a %b %d} — Week 1: {WEEK_PLAN[1]}"
    if wk > TOTAL_WEEKS:
        return "**🤖 AI sprint**\n- 16-week sprint complete 🎉"
    active = _active_days_this_week(today)
    interviews = interview_sessions_this_week(today)
    return (
        "**🤖 AI sprint**\n"
        f"- Week {wk}/{TOTAL_WEEKS} · {phase_for(wk)}\n"
        f"- This week's goal: {WEEK_PLAN.get(wk, '—')}\n"
        f"- Active days: {active}/7 · interview prep: {interviews}/{INTERVIEW_WEEKLY_TARGET}\n"
        f"- Next week: {WEEK_PLAN.get(wk + 1, '— (sprint wraps)')}"
    )


def build_in_public_draft(today: dt.date) -> list[str]:
    """Blog-draft bullets seeded from the week's commits — a ready-to-edit
    'build in public' post. Empty if nothing shipped."""
    wk = week_number(today)
    shipped = commit_log(today, days=7)
    if not shipped:
        return []
    header = f"**📣 Build-in-public draft (Sprint Wk {wk})** — edit & post:" if wk else \
        "**📣 Build-in-public draft** — edit & post:"
    lines = [header, "  - Shipped this week:"]
    lines += [f"    - {s}" for s in shipped]
    if wk and wk < TOTAL_WEEKS:
        lines.append(f"  - Next: {WEEK_PLAN.get(wk + 1, '')}")
    return ["\n".join(lines)]
