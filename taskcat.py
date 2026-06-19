"""taskcat.py — deterministic task categorization for the daily note.

The coach (LLM) is good at suggesting task *content* but terrible at *bucketing*:
it invents a new, overlapping taxonomy every day ("Morning Prep", "Body &
Errands", "Home & Wellbeing", "Other"…) and scatters the same recurring tasks
across different buckets. So we ignore its bucket names entirely and assign every
task to ONE fixed category by keyword — a stable, predictable Tasks section every
single day. This mirrors the OCR auto-categorizer the user likes.

`render_grouped` takes (text, checked) tuples (so completed tasks stay checked),
dedupes them, and emits the full Tasks body grouped in a fixed display order with
the Bills & Payments bucket always first.
"""
from __future__ import annotations

import re

from taskkeys import bill_key, is_payment_task, task_key

# Precedence order — the FIRST category whose patterns match wins, so the most
# specific categories come first (e.g. "workout" must beat the bare "work" of the
# Work bucket). Each entry: (key, heading, [lowercase substring patterns]).
CATEGORIES: list[tuple[str, str, list[str]]] = [
    ("travel", "✈️ Travel", [
        "trip", "pack", "flight", "fly", "airport", "hotel", "boarding",
        "itinerary", "tsa", "layover", "checked bag", "carry-on",
    ]),
    ("health", "🧍 Health & Body", [
        "workout", "work out", "working out", "yoga", "gym", "jog", "jogging",
        "running", "go for a run", "shave", "shower", "stretch", "meditat",
        "physical", "dentist", "doctor", "eye", "prescription", "medication",
        "meds", "pill", "therapy", "drink water", "water intake", "sleep",
        "nap", "haircut",
    ]),
    ("home", "🏠 Home & Chores", [
        "laundry", "fold", "wash", "clean", "vacuum", "dishes", "dishwasher",
        "trash", "recycling", "garbage", "sheets", "bedding", "towels", "grocer",
        "groceries", "costco", "bj's", "cook", "meal", "tofu", "marimi", "kitchen",
        "bathroom", "tidy", "declutter", "plant", "fridge", "dinner", "lunch",
        "breakfast", "brunch", "recipe",
    ]),
    ("ai", "🤖 AI & Learning", [
        "ai learning", "interview prep", "leetcode", "system design", "study",
        "course", "module", "math", "pytorch", "tensor", "rag", "fine-tun",
        "fine tun", "agent", "llm", "model", "daily-lookback", "lookback",
        "obsidian", "vault", "neural", "notebook", "dataset", "embedding",
        "read paper", "blog", "build a", "build an", "ai tooling", "experiment",
        "deep learning", "fast.ai", "huggingface", "hugging face",
    ]),
    ("money", "💰 Money & Admin", [
        "transfer", "bank", "account", "statement", "merrill", "wells fargo",
        "5/3", "fifth third", "deposit", "withdraw", "invest", "401k", "ira",
        "insurance", "renew", "license", "dmv", "registration", "oil change",
        "car ", "tax", "application", "form", "passport", "appointment", "venmo",
    ]),
    ("people", "📞 People & Errands", [
        "call", "text", "message", "reply", "pick up", "pickup", "drop off",
        "dropoff", "return", "order", "sara", "dad", "didi", "mom", "sister",
        "gift", "rsvp", "schedule", "confirm", "reach out", "email back",
    ]),
    ("work", "💼 Work", [
        "work", "meeting", "standup", "stand-up", "deploy", "ticket", "jira",
        "pr review", "pull request", "client", "deadline", "report",
        "presentation", "slides", "1:1", "sync",
    ]),
]

OTHER_HEADING = "📥 Other"
PAYMENTS_HEADING = "💸 Bills & Payments"

# Display order (top → bottom). Differs from precedence above so the most useful
# buckets lead. Every key here must exist in CATEGORIES.
DISPLAY_ORDER = ["work", "ai", "home", "health", "people", "money", "travel"]

_HEADINGS = {key: heading for key, heading, _ in CATEGORIES}

# Tells that an item is journal/message leakage, not a real task. The model
# sometimes appends "— mentioned in journal"; we drop those outright.
_NOISE_MARKERS = (
    "mentioned in journal", "mentioned in the journal", "noted in journal",
    "per journal", "from journal", "as mentioned in",
)


def is_noise_task(task: str) -> bool:
    low = task.lower()
    return any(m in low for m in _NOISE_MARKERS)


# Leading verbs that make a task a communication/errand even when it mentions food
# ("Respond to Alex about lunch" is a People task, not a Home one).
_COMMS_LEADING = (
    "call ", "text ", "reply", "respond", "confirm ", "ask ", "email ",
    "message ", "ping ", "rsvp", "remind ", "reach out", "follow up", "follow-up",
)


def categorize(task: str) -> str:
    """Fixed category key for a task. Payments are handled separately by caller."""
    low = task.lower().strip()
    for key, _heading, patterns in CATEGORIES:
        if any(p in low for p in patterns):
            # A food word shouldn't bucket a "Respond to … about lunch" comms task.
            if key == "home" and any(low.startswith(v) for v in _COMMS_LEADING):
                return "people"
            return key
    return "other"


def _identity(task: str) -> str:
    """Dedup identity: bill_key for payments (so a stale amount collapses with the
    fresh one), task_key otherwise."""
    if is_payment_task(task):
        return bill_key(task) or task_key(task)
    return task_key(task)


_DEDUP_STOP = {
    "the", "a", "an", "to", "for", "with", "and", "of", "on", "in", "about",
    "at", "details", "please", "pls", "tomorrow", "today", "her", "his",
}


def significant_words(text: str) -> set[str]:
    """Lowercase content words (≥3 chars, stopwords dropped) — the basis for
    fuzzy near-duplicate comparison."""
    return {
        w for w in re.findall(r"[a-z0-9]+", text.lower())
        if len(w) > 2 and w not in _DEDUP_STOP
    }


_word_set = significant_words  # internal alias


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def _collapse_done_redos(rec: dict, order: list[str]) -> None:
    """Drop an unchecked task that's a near-duplicate of a DONE one — the message
    pipeline re-extracts the same commitment with slightly different wording each
    run ("Check tracking for Alex's order" vs "…an order Alex placed"). Only
    checked-vs-unchecked pairs collapse, so two distinct active tasks are never
    lost. Payments are never touched (different cards can read alike)."""
    removed: set[str] = set()
    sets = {i: _word_set(rec[i][0]) for i in order}
    for a in order:
        if a in removed or rec[a][2] or not sets[a]:
            continue
        for b in order:
            if b == a or b in removed or rec[b][2] or not sets[b]:
                continue
            if rec[a][1] == rec[b][1]:  # need exactly one done, one not
                continue
            jac = len(sets[a] & sets[b]) / len(sets[a] | sets[b])
            if jac < 0.5:
                continue
            done, redo = (a, b) if rec[a][1] else (b, a)
            rec[done][1] = True
            removed.add(redo)
    order[:] = [i for i in order if i not in removed]


def _clean(text: str) -> str:
    text = text.strip().lstrip("-").strip()
    if text.startswith("[ ]"):
        text = text[3:].strip()
    elif text.startswith("[x]"):
        text = text[3:].strip()
    return text


def render_grouped(
    tasks: list[tuple[str, bool]],
    required: list[str] | None = None,
) -> list[str]:
    """Full Tasks-section body, deterministically bucketed.

    `tasks` is (text, checked) — existing note lines keep their checked state and
    coach suggestions come in unchecked. `required` items are forced in and their
    wording is canonical (so a bill's fresh amount overrides a stale carried copy).
    Dedupes by identity; checked wins if any copy was checked.
    """
    from note_io import is_reminder_echo  # local import avoids a circular import

    required = required or []
    req_by_key = {task_key(r): r for r in required if r and task_key(r)}

    rec: dict[str, list] = {}  # identity -> [text, checked, is_payment]
    order: list[str] = []

    def put(raw: str, checked: bool, canonical: bool = False) -> None:
        text = _clean(raw)
        if not text or is_reminder_echo(text) or is_noise_task(text):
            return
        # Canonicalize wording to the REQUIRED version when keys match.
        text = req_by_key.get(task_key(text), text)
        ident = _identity(text)
        if not ident:
            return
        if ident in rec:
            rec[ident][1] = rec[ident][1] or checked
            if canonical:
                rec[ident][0] = text
        else:
            rec[ident] = [text, checked, is_payment_task(text)]
            order.append(ident)

    for text, checked in tasks:
        put(text, checked)
    for r in required:
        put(r, False, canonical=True)

    _collapse_done_redos(rec, order)

    payments = [i for i in order if rec[i][2]]
    by_cat: dict[str, list[str]] = {}
    for ident in order:
        if rec[ident][2]:
            continue
        by_cat.setdefault(categorize(rec[ident][0]), []).append(ident)

    out: list[str] = []

    def emit(heading: str, idents: list[str]) -> None:
        if not idents:
            return
        if out:
            out.append("")
        out.append(f"**{heading}**")
        for ident in idents:
            text, checked, _ = rec[ident]
            out.append(f"- [{'x' if checked else ' '}] {text}")

    emit(PAYMENTS_HEADING, payments)
    for key in DISPLAY_ORDER:
        emit(_HEADINGS[key], by_cat.get(key, []))
    emit(OTHER_HEADING, by_cat.get("other", []))
    return out
