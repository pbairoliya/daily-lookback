"""runstate.py — last-run tracking, catch-up planning, heartbeat ping."""
from __future__ import annotations

import datetime as dt
import json
import urllib.request
from pathlib import Path

from config import HEARTBEAT_URL

STATE_DIR = Path("~/.local/state/daily-lookback").expanduser()
LAST_RUN_FILE = STATE_DIR / "last_run"
# Grow-only store of (sender_stem, subject_stem) the user told us to ignore.
# Persisted because the daily note's Reminders section is regenerated each run,
# which would otherwise erase the "ignore" annotation that line carried.
IGNORED_FILE = STATE_DIR / "ignored.json"


def read_ignored() -> set[tuple[str, str]]:
    try:
        raw = json.loads(IGNORED_FILE.read_text())
    except (FileNotFoundError, ValueError):
        return set()
    return {(str(a), str(b)) for a, b in raw if isinstance(a, str) or isinstance(b, str)}


def write_ignored(keys: set[tuple[str, str]]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    IGNORED_FILE.write_text(json.dumps(sorted(list(k) for k in keys)))


# Grow-only store of paid bills, keyed (payee_core, cycle_month "YYYY-MM").
# Persisted so a bill checked off on one day's note isn't regenerated as
# unchecked the next — while next month's statement (new cycle) still shows.
PAID_BILLS_FILE = STATE_DIR / "paid_bills.json"


def read_paid_bills() -> set[tuple[str, str]]:
    try:
        raw = json.loads(PAID_BILLS_FILE.read_text())
    except (FileNotFoundError, ValueError):
        return set()
    return {(str(a), str(b)) for a, b in raw}


def write_paid_bills(keys: set[tuple[str, str]]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    PAID_BILLS_FILE.write_text(json.dumps(sorted(list(k) for k in keys)))


# Grow-only store of message-derived task "signatures" (sorted content words)
# already surfaced into a note. The same iMessage stays in the lookback window for
# days and the LLM rewords it each run, so without this the same commitment
# re-appears as a fresh task daily. Once surfaced, carry-over keeps it alive while
# unchecked; we never re-add a near-duplicate. Capped so it can't grow unbounded.
SEEN_MSGTASKS_FILE = STATE_DIR / "seen_msgtasks.json"
_SEEN_MSGTASKS_CAP = 300


def read_seen_msgtasks() -> list[set[str]]:
    try:
        raw = json.loads(SEEN_MSGTASKS_FILE.read_text())
    except (FileNotFoundError, ValueError):
        return []
    return [set(map(str, sig)) for sig in raw if isinstance(sig, list)]


def write_seen_msgtasks(sigs: list[set[str]]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    trimmed = sigs[-_SEEN_MSGTASKS_CAP:]
    SEEN_MSGTASKS_FILE.write_text(json.dumps([sorted(s) for s in trimmed]))


def read_last_run() -> dt.date | None:
    try:
        return dt.date.fromisoformat(LAST_RUN_FILE.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def write_last_run(d: dt.date) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    LAST_RUN_FILE.write_text(d.isoformat())


def dates_to_backfill(
    today: dt.date, last_run: dt.date | None, max_days: int = 7
) -> list[dt.date]:
    """Dates needing a run: everything after last_run through today, capped.

    No recorded history → just today (don't guess how far back to go).
    Already ran today → nothing.
    """
    if last_run is None:
        return [today]
    if last_run >= today:
        return []
    start = max(last_run + dt.timedelta(days=1), today - dt.timedelta(days=max_days - 1))
    return [start + dt.timedelta(days=i) for i in range((today - start).days + 1)]


def ping_heartbeat(ok: bool) -> None:
    """Best-effort dead-man's-switch ping (healthchecks.io style).

    Success pings the configured URL; failure pings <url>/fail so the
    monitor can alert immediately instead of waiting for the grace period.
    Never raises — a down network must not fail the run.
    """
    if not HEARTBEAT_URL:
        return
    url = HEARTBEAT_URL if ok else f"{HEARTBEAT_URL.rstrip('/')}/fail"
    try:
        with urllib.request.urlopen(url, timeout=10):
            pass
    except Exception as e:  # noqa: BLE001
        print(f"Heartbeat ping failed ({e}); continuing.")
