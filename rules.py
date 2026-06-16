"""rules.py — deterministic life rules (shave, laundry, cadence)."""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

from config import NUDGE_AFTER_DAYS
from note_io import FOCUS_HEADING, REMINDERS_HEADING, is_reminder_echo
from taskkeys import PAYMENT_PREFIXES, bill_key, is_payment_task, task_key
from vault import RECURRING_TASKS, extract_section, parse_tasks, read_note, recent_notes

CADENCE_TASKS: list[dict] = [
    {
        "label": "Fold and put away laundry",
        "patterns": ["fold", "folded", "put away laundry"],
        "days": 7,
    },
    {
        "label": "Grocery run (Costco / BJ's / store)",
        "patterns": ["grocer", "groceries", "bj's", "bjs", "costco", "trader joe", "wegmans"],
        "days": 14,
    },
    {"label": "Wash sheets and towels", "patterns": ["sheets", "bedding", "towels"], "days": 14},
    {"label": "Deep clean the apartment", "patterns": ["deep clean", "vacuum", "clean apartment"], "days": 14},
    {
        "label": "Quick clean — kitchen & bathroom wipe-down",
        "patterns": ["kitchen clean", "bathroom clean", "wipe down", "quick clean"],
        "days": 7,
    },
    {
        "label": "Take out trash and recycling",
        "patterns": ["trash", "recycling", "garbage"],
        "days": 7,
    },
    {
        "label": "Pay credit card bill(s)",
        "patterns": [
            "credit card", "pay chase", "pay amex", "pay citi", "card payment",
            "paid credit card", "credit card bill",
        ],
        "days": 30,
    },
    {
        "label": "Pay apartment rent / building bill",
        "patterns": [
            "rent", "paid rent", "apartment payment", "building payment", "landlord",
        ],
        "days": 30,
    },
    {"label": "Oil change", "patterns": ["oil change"], "days": 90},
    {"label": "Annual physical", "patterns": ["physical appointment", "annual physical"], "days": 365},
]
CADENCE_LOOKBACK_DAYS = 120

SHAVE_WEEKDAYS = {0, 2, 4, 6}
SHAVE_MIN_GAP_DAYS = 2
SHAVE_PATTERNS = ["shave", "shaved", "shaving"]
SHAVE_LABEL = "Shave"

LAUNDRY_FOLD_PATTERNS = ["fold", "folded", "put away laundry"]
LAUNDRY_WASH_PATTERNS = ["wash a load", "do laundry", "wash laundry", "start a wash", "run laundry"]
LAUNDRY_ALL_PATTERNS = LAUNDRY_FOLD_PATTERNS + LAUNDRY_WASH_PATTERNS + ["laundry"]
LAUNDRY_QUIET_DAYS = 4
LAUNDRY_FOLD_LABEL = "Fold and put away laundry"

SCHEDULED_LOOKBACK_DAYS = 21


def _note_date(path: Path) -> dt.date | None:
    try:
        return dt.date.fromisoformat(path.stem)
    except ValueError:
        return None


def matches_word(text: str, patterns: list[str]) -> bool:
    low = text.lower()
    return any(re.search(rf"\b{re.escape(p.lower())}\b", low) for p in patterns)


def _last_completion(today: dt.date, patterns: list[str], lookback_days: int) -> dt.date | None:
    cutoff = today - dt.timedelta(days=lookback_days)
    for note in recent_notes(lookback_days + 5):
        nd = _note_date(note)
        if nd is None or nd >= today or nd < cutoff:
            continue
        done, _ = parse_tasks(read_note(note))
        if any(matches_word(d, patterns) for d in done):
            return nd
    return None


def due_cadence_tasks(
    today: dt.date,
    carry: list[str],
    *,
    skip_laundry: bool = False,
) -> list[tuple[str, int | None]]:
    cutoff = today - dt.timedelta(days=CADENCE_LOOKBACK_DAYS)
    notes = recent_notes(CADENCE_LOOKBACK_DAYS + 5)
    carry_lower = [c.lower() for c in carry]

    last_done: dict[int, dt.date] = {}
    for note in notes:
        nd = _note_date(note)
        if nd is None or nd < cutoff or nd >= today:
            continue
        done, _not_done = parse_tasks(read_note(note))
        done_lower = [d.lower() for d in done]
        for i, rule in enumerate(CADENCE_TASKS):
            if i in last_done:
                continue
            patterns = [p.lower() for p in rule["patterns"]]
            if any(p in d for d in done_lower for p in patterns):
                last_done[i] = nd

    due: list[tuple[str, int | None]] = []
    for i, rule in enumerate(CADENCE_TASKS):
        if skip_laundry and rule["label"] == LAUNDRY_FOLD_LABEL:
            continue
        patterns = [p.lower() for p in rule["patterns"]]
        if any(p in c for c in carry_lower for p in patterns):
            continue
        last = last_done.get(i)
        if last is None:
            continue
        days_since = (today - last).days
        if days_since >= rule["days"]:
            due.append((rule["label"], days_since))
    return due


def shave_due(today: dt.date) -> bool:
    if today.weekday() not in SHAVE_WEEKDAYS:
        return False
    last = _last_completion(today, SHAVE_PATTERNS, SCHEDULED_LOOKBACK_DAYS)
    if last is None:
        return True
    return (today - last).days >= SHAVE_MIN_GAP_DAYS


def laundry_quiet(today: dt.date) -> bool:
    last_fold = _last_completion(today, LAUNDRY_FOLD_PATTERNS, SCHEDULED_LOOKBACK_DAYS)
    if last_fold is None:
        return False
    return (today - last_fold).days < LAUNDRY_QUIET_DAYS


def _next_shave_day(today: dt.date) -> dt.date | None:
    for i in range(1, 8):
        d = today + dt.timedelta(days=i)
        if d.weekday() in SHAVE_WEEKDAYS:
            return d
    return None


def suppression_notes(today: dt.date) -> list[str]:
    out: list[str] = []
    if not shave_due(today):
        last = _last_completion(today, SHAVE_PATTERNS, SCHEDULED_LOOKBACK_DAYS)
        if today.weekday() not in SHAVE_WEEKDAYS:
            reason = f"{today.strftime('%A')} isn't a permitted shave day (Mon/Wed/Fri/Sun)"
        elif last is not None:
            reason = (
                f"already shaved {last.strftime('%a %b %d')} "
                f"({(today - last).days}d ago; min gap {SHAVE_MIN_GAP_DAYS}d)"
            )
        else:
            reason = "suppressed"
        nxt = _next_shave_day(today)
        tail = f"; next permitted {nxt.strftime('%A %b %d')}" if nxt else ""
        out.append(f"No shave today — {reason}{tail}.")

    if laundry_quiet(today):
        last_fold = _last_completion(today, LAUNDRY_FOLD_PATTERNS, SCHEDULED_LOOKBACK_DAYS)
        if last_fold is not None:
            until = last_fold + dt.timedelta(days=LAUNDRY_QUIET_DAYS)
            out.append(
                f"Laundry quiet — folded {last_fold.strftime('%a %b %d')}; "
                f"no fold/wash until {until.strftime('%a %b %d')}."
            )
    return out


def recent_completions(today: dt.date, days: int = 3, cap: int = 6) -> list[str]:
    """Recently completed one-offs for the Looking back digest, newest first.

    The block 'slowly trims out': a completion shows in full the next day, then
    fewer survive each day as they age (older day → fewer kept), and the whole
    list is capped so Looking back never accumulates. Recurring habits and
    duplicates are excluded.
    """
    dated = sorted(
        ((n, _note_date(n)) for n in recent_notes(days + 2)),
        key=lambda pair: pair[1] or dt.date.min,
        reverse=True,  # newest day first so the freshest completions win the cap
    )
    out: list[str] = []
    seen: set[str] = set()
    for note, nd in dated:
        if nd is None:
            continue
        age = (today - nd).days
        if age <= 0 or age > days:
            continue
        per_day = max(1, days - age + 1)  # 3d window: yesterday 3, then 2, then 1
        kept = 0
        done, _ = parse_tasks(read_note(note))
        for d in done:
            t = d.strip()
            if not t or t in RECURRING_TASKS:
                continue
            key = normalize_task(t)
            if key in seen:
                continue
            seen.add(key)
            out.append(f"{nd.strftime('%a %b %d')}: {t}")
            kept += 1
            if kept >= per_day or len(out) >= cap:
                break
        if len(out) >= cap:
            break
    return out


# How long a completed one-off task stays suppressed before it may resurface.
GRACE_DAYS = 2


def normalize_task(s: str) -> str:
    """Lowercase, strip checkbox punctuation/emoji — for comparing task text."""
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()


def recently_completed(today: dt.date, days: int = GRACE_DAYS) -> set[str]:
    """Normalized text of NON-recurring tasks completed within the grace window.

    These should not be re-suggested or carried over again so soon (e.g. you just
    recorded the Influenster video yesterday — don't put it back on today's list).
    Recurring habits (Work, Workout…) are excluded so they still appear daily.
    """
    out: set[str] = set()
    for note in recent_notes(days + 2):
        nd = _note_date(note)
        if nd is None or nd >= today or (today - nd).days > days:
            continue
        done, _ = parse_tasks(read_note(note))
        for d in done:
            t = d.strip()
            if t and t not in RECURRING_TASKS:
                out.add(normalize_task(t))
    return out


def task_ages(today: dt.date, lookback_days: int = 14) -> list[tuple[str, int]]:
    """(task text, consecutive days unchecked ending yesterday), oldest first.

    A streak counts how many days in a row a non-recurring task sat unchecked
    in the daily notes. A missing note breaks every streak (no guessing
    across gaps).
    """
    notes_by_date: dict[dt.date, Path] = {}
    for note in recent_notes(lookback_days + 5):
        nd = _note_date(note)
        if nd is not None:
            notes_by_date[nd] = note

    yesterday = today - dt.timedelta(days=1)
    if yesterday not in notes_by_date:
        return []
    _done, open_tasks = parse_tasks(read_note(notes_by_date[yesterday]))
    streaks: dict[str, int] = {}
    texts: dict[str, str] = {}
    for raw in open_tasks:
        t = raw.strip()
        if not t or t in RECURRING_TASKS or is_reminder_echo(t):
            continue
        k = task_key(t)
        if k and k not in streaks:
            streaks[k] = 1
            texts[k] = t

    alive = set(streaks)
    for i in range(2, lookback_days + 1):
        if not alive:
            break
        note = notes_by_date.get(today - dt.timedelta(days=i))
        if note is None:
            break
        _d, older_open = parse_tasks(read_note(note))
        keys = {task_key(t.strip()) for t in older_open if t.strip()}
        for k in list(alive):
            if k in keys:
                streaks[k] += 1
            else:
                alive.discard(k)
    return sorted(
        ((texts[k], n) for k, n in streaks.items()), key=lambda kv: -kv[1]
    )


def slipped_tasks(today: dt.date, k: int = NUDGE_AFTER_DAYS) -> list[tuple[str, int]]:
    """Tasks that have carried over k+ consecutive days — nudge material."""
    return [(t, n) for t, n in task_ages(today) if n >= k]


def forbidden_items(notes: list[Path]) -> list[str]:
    out: dict[str, None] = {}
    for note in notes:
        text = read_note(note)
        done, _not_done = parse_tasks(text)
        for d in done:
            t = d.strip()
            if t and t not in RECURRING_TASKS:
                out.setdefault(t, None)
        for line in extract_section(text, FOCUS_HEADING).split("\n"):
            s = line.strip().lstrip("-").strip()
            if s and not s.startswith(">"):
                out.setdefault(s, None)
    return list(out.keys())


# --- "ignore" convention -------------------------------------------------
# In a daily note's 🔔 Reminders section the user annotates an email line with
# the word "ignore" ("(ignore)", "ignore next time", "… Ignore") to mean: stop
# surfacing this email — and ones like it from the same sender — in future runs.
# We scan recent notes for those lines and suppress matching mail next time.

_IGNORE_RE = re.compile(r"\bignore", re.IGNORECASE)
# An email reminder line looks like: - [x] **Sender** [cat] — "Subject" — why
_MAIL_LINE_RE = re.compile(r"\*\*(?P<who>[^*]+)\*\*.*?[\"“](?P<subj>[^\"”]+)[\"”]")
_MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec"


def ignore_stem(s: str) -> str:
    """Stable comparison stem: drop dates/digits/punctuation so a templated
    subject ('6 boxes sent on Jun 14, 2026') still matches next week's copy."""
    s = s.lower()
    s = re.sub(rf"\b(?:{_MONTHS})[a-z]* ?\d{{0,2}},? ?\d{{0,4}}", " ", s)
    s = re.sub(r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b", " ", s)
    s = re.sub(r"\d+", " ", s)
    s = re.sub(r"[^a-z ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def ignored_email_keys(today: dt.date, days: int = 30) -> set[tuple[str, str]]:
    """(sender_stem, subject_stem) pairs the user marked 'ignore'.

    Scans recent notes for fresh 'ignore' annotations and merges them into a
    persistent grow-only store, so an ignore survives the nightly regeneration
    of the Reminders section (which erases the annotated line). Returns the
    full union. Delete ~/.local/state/daily-lookback/ignored.json to reset.
    """
    from runstate import read_ignored, write_ignored

    found: set[tuple[str, str]] = set()
    for note in recent_notes(days + 2):
        nd = _note_date(note)
        if nd is None or nd > today or (today - nd).days > days:
            continue
        body = extract_section(read_note(note), REMINDERS_HEADING)
        for line in body.split("\n"):
            if not _IGNORE_RE.search(line):
                continue
            mm = _MAIL_LINE_RE.search(line)
            if not mm:
                continue
            who = normalize_task(mm.group("who"))
            subj = ignore_stem(mm.group("subj"))
            if who:
                found.add((who, subj))

    stored = read_ignored()
    merged = stored | found
    if merged != stored:
        write_ignored(merged)
    return merged


# --- paid-bill suppression ----------------------------------------------
# A bill the user checked off ("paid") must not regenerate as unchecked the
# next day. We key on (payee_core, cycle_month) so paying June's statement
# suppresses only June's — next month's statement (new cycle) still appears.

_MONTH_NUM = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_BILL_NUMERIC_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b")
_BILL_MONTH_DATE = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+"
    r"\d{1,2}(?:st|nd|rd|th)?(?:,?\s*(\d{4}))?",
    re.IGNORECASE,
)


def bill_payee_core(s: str) -> str | None:
    """Coarse payee identity, card last-4 dropped: 'Pay credit card — Bank of
    America …2222 ($2,500, due Jun 12)' -> 'bank of america'. None if not a bill."""
    bk = bill_key(s)
    if not bk:
        return None
    core = bk
    for p in PAYMENT_PREFIXES:
        if core.startswith(p):
            core = core[len(p):].strip()
            break
    core = re.sub(r"\b\d{2,4}\b", "", core)  # drop card last-4 / acct digits
    return re.sub(r"\s+", " ", core).strip() or bk


def bill_cycle_month(text: str, ref: dt.date) -> str:
    """Billing cycle as 'YYYY-MM' — from a due date in the text, else `ref`'s
    month (when the bill was paid / generated)."""
    m = _BILL_NUMERIC_DATE.search(text)
    if m and 1 <= int(m.group(1)) <= 12:
        month = int(m.group(1))
        yr = m.group(3)
        year = (int(yr) + 2000 if yr and int(yr) < 100 else int(yr)) if yr else ref.year
        return f"{year:04d}-{month:02d}"
    m = _BILL_MONTH_DATE.search(text)
    if m:
        month = _MONTH_NUM[m.group(1).lower()[:3]]
        year = int(m.group(2)) if m.group(2) else ref.year
        return f"{year:04d}-{month:02d}"
    return f"{ref.year:04d}-{ref.month:02d}"


def paid_bill_keys(today: dt.date, days: int = 45) -> set[tuple[str, str]]:
    """(payee_core, cycle_month) for bills checked off in recent notes, merged
    into a persistent grow-only store so 'paid' survives note regeneration."""
    from runstate import read_paid_bills, write_paid_bills

    found: set[tuple[str, str]] = set()
    for note in recent_notes(days + 2):
        nd = _note_date(note)
        if nd is None or nd > today or (today - nd).days > days:
            continue
        done, _ = parse_tasks(read_note(note))
        for t in done:
            if not is_payment_task(t):
                continue
            core = bill_payee_core(t)
            if core:
                found.add((core, bill_cycle_month(t, nd)))

    stored = read_paid_bills()
    merged = stored | found
    if merged != stored:
        write_paid_bills(merged)
    return merged


def is_paid_bill(text: str, today: dt.date, paid: set[tuple[str, str]]) -> bool:
    """True when this generated bill's payee+cycle was already paid."""
    if not paid:
        return False
    core = bill_payee_core(text)
    return bool(core) and (core, bill_cycle_month(text, today)) in paid


def is_ignored_mail(mail: dict, ignored: set[tuple[str, str]]) -> bool:
    """True when this email matches an 'ignore' annotation: same sender, and
    same subject stem (or the user ignored that sender with a templated subject
    whose stem is a prefix of this one)."""
    if not ignored:
        return False
    who = normalize_task(mail.get("payee") or mail.get("from", ""))
    subj = ignore_stem(mail.get("subject", ""))
    for ig_who, ig_subj in ignored:
        if not ig_who or ig_who not in who and who not in ig_who:
            continue
        if not ig_subj or subj == ig_subj or subj.startswith(ig_subj) or ig_subj.startswith(subj):
            return True
    return False
