#!/usr/bin/env python3
"""Stress-test Google Calendar + Gmail integration.

Run after `uv run python google_auth.py`:
    uv run python stress_test.py
    uv run python stress_test.py --triage   # also run Ollama email triage
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import time

import google_auth
import reminders
from coach import wait_for_ollama
from config import DEFAULT_MODEL, OLLAMA_URL


def _section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def main() -> int:
    p = argparse.ArgumentParser(description="Stress-test Calendar + Gmail pulls.")
    p.add_argument("--date", help="Anchor date YYYY-MM-DD (default: today).")
    p.add_argument("--triage", action="store_true", help="Run Ollama email triage.")
    p.add_argument("--model", default=DEFAULT_MODEL)
    args = p.parse_args()

    target = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    anchor = dt.datetime.combine(target, dt.time(8, 0))

    _section("Auth")
    if not google_auth.is_configured():
        print("FAIL: credentials.json missing. See INTEGRATIONS_PLAN.md §3.")
        return 1
    print("credentials.json: OK")
    if not google_auth.TOKEN.exists():
        print("FAIL: token.json missing. Run: uv run python google_auth.py")
        return 1
    print("token.json: OK")

    _section("Calendar")
    print(
        f"Window: −{reminders.CALENDAR_LOOKBACK_DAYS}d to "
        f"+{reminders.CALENDAR_LOOKAHEAD_DAYS}d from {target}"
    )
    t0 = time.monotonic()
    events = reminders.calendar_events(anchor)
    elapsed = time.monotonic() - t0
    print(f"Fetched {len(events)} events in {elapsed:.2f}s")
    by_day: dict[dt.date, int] = {}
    trips = 0
    for e in events:
        d = e["start"].date()
        by_day[d] = by_day.get(d, 0) + 1
        if e.get("is_trip"):
            trips += 1
    for d in sorted(by_day):
        mark = " <-- anchor" if d == target else ""
        print(f"  {d}: {by_day[d]} event(s){mark}")
    print(f"Trips in window: {trips}")
    today = reminders.events_on_date(events, target)
    print(f"Today ({target}): {len(today)} event(s)")
    for e in today[:5]:
        print(f"  · {e['summary']}")

    _section("Gmail — general query")
    print(f"Query: {reminders.GMAIL_QUERY_GENERAL[:80]}…")
    t0 = time.monotonic()
    general_ids = reminders._gmail_list(
        google_auth.gmail_client(),
        reminders.GMAIL_QUERY_GENERAL,
        reminders.GMAIL_MAX_CANDIDATES // 2,
    )
    print(f"General hits: {len(general_ids)} in {time.monotonic() - t0:.2f}s")

    _section("Gmail — bills query")
    print(f"Query: {reminders.GMAIL_QUERY_BILLS[:80]}…")
    t0 = time.monotonic()
    bill_ids = reminders._gmail_list(
        google_auth.gmail_client(),
        reminders.GMAIL_QUERY_BILLS,
        reminders.GMAIL_MAX_CANDIDATES // 2,
    )
    print(f"Bill hits: {len(bill_ids)} in {time.monotonic() - t0:.2f}s")

    _section("Gmail — merged candidates")
    t0 = time.monotonic()
    raw = reminders.candidate_emails()
    print(f"Merged unique: {len(raw)} in {time.monotonic() - t0:.2f}s")
    by_cat: dict[str, int] = {}
    for m in raw:
        c = m.get("category", "?")
        by_cat[c] = by_cat.get(c, 0) + 1
    print(f"By category: {by_cat}")
    for m in raw[:8]:
        print(
            f"  [{m.get('category')}] {reminders._short_from(m['from'])} — "
            f"{m['subject'][:55]}"
        )

    mails = raw
    if args.triage and raw:
        _section("Ollama triage")
        wait_for_ollama()
        t0 = time.monotonic()
        mails = reminders.triage_emails(raw, args.model, OLLAMA_URL)
        print(f"Triaged to {len(mails)} actionable in {time.monotonic() - t0:.2f}s")
        for m in mails:
            bill = " [bill]" if m.get("is_bill") else ""
            print(f"  {bill} {reminders._short_from(m.get('from', ''))} — {m.get('subject', '')[:50]}")

    _section("Bill → REQUIRED tasks")
    tasks = reminders.bill_tasks_from_emails(mails, target)
    if tasks:
        for t in tasks:
            print(f"  · {t}")
    else:
        print("  (none — no bill mail in window)")

    _section("Coach context preview")
    ctx = reminders.format_coach_context(
        events, mails, target, journal_seeds=reminders.trip_journal_seeds(events, target)
    )
    print(ctx or "(empty)")

    _section("Summary")
    print("PASS — Google APIs responded.")
    if not events and not raw:
        print("WARN: zero calendar events and zero emails; check account / queries.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
