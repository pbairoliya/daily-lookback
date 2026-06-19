"""
lookback.py — daily note orchestrator.

Reads recent Obsidian daily notes, applies deterministic life rules, pulls
Google Calendar + Gmail, asks a local Ollama model for a structured plan,
and writes into today's daily note (idempotent).

Run:
    uv run lookback.py [--dry-run] [--date YYYY-MM-DD] [--days N] [--model NAME]
"""
from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

import aijourney
import imessage
import reminders
import taskcat
import weekly
from coach import ask_coach, as_list, shutdown_ollama, wait_for_ollama
from config import (
    BACKFILL_MODE,
    DAILY_DIR,
    DEFAULT_MODEL,
    MAX_BACKFILL_DAYS,
    OLLAMA_URL,
    RECEIPTS_ENABLED,
    RECEIPTS_LOOKBACK_DAYS,
    WEEKLY_ENABLED,
)
from receipts_feed import recent_receipts, render_receipt_lines
from runstate import (
    dates_to_backfill,
    ping_heartbeat,
    read_last_run,
    read_seen_msgtasks,
    write_last_run,
    write_seen_msgtasks,
)
from note_io import (
    AIJOURNEY_HEADING,
    BLOG_HEADING,
    FOCUS_HEADING,
    JOURNAL_HEADING,
    LOOKBACK_HEADING,
    REMINDERS_HEADING,
    TASKS_HEADING,
    TOMORROW_HEADING,
    WINS_HEADING,
    append_tasks,
    extract_task_states,
    fill_if_empty,
    inject_section,
    is_tasks_pristine,
    note_path_for,
    refresh_prompts,
    is_reminder_echo,
    render_task_groups,
    render_template,
    replace_section_body,
    strip_reminder_echoes,
    strip_unchecked_in_set,
    strip_unchecked_tasks,
    strip_unchecked_where,
    tasks_missing_from_note,
    upsert_tasks,
)
from taskkeys import bill_key, dedup_by_key, task_key
from rules import (
    LAUNDRY_ALL_PATTERNS,
    LAUNDRY_FOLD_LABEL,
    SHAVE_LABEL,
    SHAVE_PATTERNS,
    due_cadence_tasks,
    forbidden_items,
    ignored_email_keys,
    is_paid_bill,
    laundry_quiet,
    matches_word,
    paid_bill_keys,
    normalize_task,
    recent_completions,
    recently_completed,
    shave_due,
    slipped_tasks,
    suppression_notes,
)
from vault import (
    LEARNINGS_HEADING,
    RECURRING_TASKS,
    extract_section,
    parse_tasks,
    read_note,
    recent_notes,
    section_items,
)


def build_context(notes: list[Path], days: int) -> str:
    """Digest from past Obsidian daily notes for the coach.

    Live Calendar + Gmail for *today* are NOT here — they are fetched later and
    passed as EXTERNAL (see reminders.format_coach_context) and written to
    ## 🔔 Reminders via inject_section. This function only surfaces what you
    already had in prior notes (including their archived Reminders blocks).
    """
    # Per-section caps keep the 5-day digest well under the model context
    # window — an overflowing prompt silently truncates the system prompt
    # and the coach stops returning the full schema.
    cap = 600
    chunks: list[str] = []
    for note in notes[:days]:
        text = read_note(note)
        done, not_done = parse_tasks(text)
        completed = [t for t in done if t not in RECURRING_TASKS][:12]
        carry = [t for t in not_done if t not in RECURRING_TASKS][:12]
        journal = extract_section(text, JOURNAL_HEADING).strip()[:cap]
        focus = extract_section(text, FOCUS_HEADING).strip()[:cap]
        tomorrow = extract_section(text, TOMORROW_HEADING).strip()[:cap]
        learnings = extract_section(text, LEARNINGS_HEADING).strip()[:cap]
        wins = extract_section(text, WINS_HEADING).strip()[:cap]
        prior_reminders = _prior_reminders_excerpt(text)
        chunks.append(
            f"## {note.stem}\n"
            f"Prior focus (DONE / historical — do not re-suggest):\n{focus or '(empty)'}\n\n"
            f"Prior auto-reminders (that day's saved pull — NOT today's live calendar):\n"
            f"{prior_reminders or '(none)'}\n\n"
            f"Journal (REFLECTION — already happened; NEVER turn into tasks):\n{journal or '(empty)'}\n\n"
            f"Learnings (REFLECTION — already happened; NEVER turn into tasks):\n{learnings or '(empty)'}\n\n"
            f"Wins & Gratitude (REFLECTION — already happened; NEVER turn into tasks):\n{wins or '(empty)'}\n\n"
            f"Tomorrow notes (the user's own prep for today — already fed into REQUIRED tasks):\n{tomorrow or '(empty)'}\n\n"
            f"Completed tasks (already shipped — do not re-suggest):\n"
            + ("\n".join(f"- {t}" for t in completed) if completed else "(none)")
            + "\n\nUnfinished tasks (candidates for carry-over):\n"
            + ("\n".join(f"- {t}" for t in carry) if carry else "(none)")
        )
    return "\n\n---\n\n".join(chunks)


def _prior_reminders_excerpt(note_text: str, max_lines: int = 12) -> str:
    """Trim prior ## 🔔 Reminders body for the vault digest (skip boilerplate)."""
    body = extract_section(note_text, REMINDERS_HEADING).strip()
    if not body:
        return ""
    lines: list[str] = []
    for line in body.split("\n"):
        s = line.strip()
        if not s or s.startswith(">") or s == "-":
            continue
        if "nothing pulled" in s.lower() or "credentials.json" in s.lower():
            continue
        lines.append(line.rstrip())
        if len(lines) >= max_lines:
            lines.append("  …")
            break
    return "\n".join(lines)


def carry_over_tasks(notes: list[Path]) -> list[str]:
    """Unchecked tasks from recent notes, deduped by task_key (newest text wins)."""
    seen: dict[str, str] = {}
    for note in notes:  # newest first
        _done, not_done = parse_tasks(read_note(note))
        for raw in not_done:
            t = raw.strip()
            if t and t not in RECURRING_TASKS:
                seen.setdefault(task_key(t) or t.lower(), t)
    return list(seen.values())


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate today's daily note.")
    p.add_argument("--date", help="Target date YYYY-MM-DD (default: today).")
    p.add_argument("--days", type=int, default=5, help="How many recent notes to read.")
    p.add_argument("--model", default=DEFAULT_MODEL, help="Ollama model name.")
    p.add_argument("--dry-run", action="store_true", help="Print, don't write.")
    p.add_argument(
        "--catch-up",
        action="store_true",
        help="Backfill days missed since the last successful run, then do today.",
    )
    p.add_argument(
        "--check-imessage",
        action="store_true",
        help="Self-test chat.db access (Full Disk Access) and exit.",
    )
    p.add_argument(
        "--weekly",
        action="store_true",
        help="Force the Weekly Reflection section (otherwise Sundays only).",
    )
    return p.parse_args()


def run_for_date(target: dt.date, args: argparse.Namespace) -> bool:
    target_stem = target.isoformat()

    notes = [n for n in recent_notes(args.days + 1) if n.stem != target_stem][: args.days]
    if not notes:
        print(f"No recent notes found in {DAILY_DIR}")
        return False

    print(f"Reading {len(notes)} recent notes…")
    context = build_context(notes, args.days)
    carry = carry_over_tasks(notes)
    forbidden = forbidden_items(notes)

    # Grace period: a non-recurring task completed in the last couple of days must
    # not be carried over or re-suggested (e.g. the Influenster video you just did).
    done_recent = recently_completed(target)
    if done_recent:
        carry = [c for c in carry if normalize_task(c) not in done_recent]
    # Drop email/reminder lines that a prior buggy note left in its Tasks, so they
    # don't carry forward as fake tasks (inbox items belong in 🔔 Reminders).
    carry = [c for c in carry if not is_reminder_echo(c)]
    # Auto-generated trip prep/pack lines are date-anchored ("…for tomorrow",
    # "…in 2 days") — carrying them means nagging to pack for a finished trip. Drop
    # them from carry; they're re-derived from the calendar while a trip is upcoming.
    carry = [c for c in carry if not reminders.is_trip_prep_task(c)]

    # Yesterday's 🔜 Tomorrow notes are intentions for today — feed them in as task
    # candidates so the plan reflects what the user actually lined up (not just the
    # coach's guesses). Grace-filtered and capped so it can't flood the list.
    tomorrow_carry = [
        t
        for t in section_items(read_note(notes[0]), TOMORROW_HEADING)
        if normalize_task(t) not in done_recent and not is_reminder_echo(t)
    ][:6]
    if tomorrow_carry:
        print("From yesterday's Tomorrow: " + ", ".join(tomorrow_carry[:4]))

    quiet = laundry_quiet(target)
    cadence_due = due_cadence_tasks(target, carry, skip_laundry=quiet)
    if cadence_due:
        summary = ", ".join(f"{label} ({days}d)" for label, days in cadence_due)
        print(f"Cadence reminders due: {summary}")
    cadence_labels = [label for label, _ in cadence_due]

    events: list[dict] = []
    mails: list[dict] = []
    journal_seeds: list[str] = []
    morning = dt.datetime.combine(target, dt.time(8, 0))
    try:
        events, journal_seeds = reminders.load_calendar(morning, target)
        print(
            f"Calendar: {len(events)} events "
            f"(−{reminders.CALENDAR_LOOKBACK_DAYS}d / +{reminders.CALENDAR_LOOKAHEAD_DAYS}d)"
        )
    except Exception as e:  # noqa: BLE001
        print(f"Calendar fetch failed ({e}); continuing without events.")

    scheduled: list[str] = []
    scheduled.extend(tomorrow_carry)
    forbidden_extra: list[str] = []
    if shave_due(target):
        scheduled.append(SHAVE_LABEL)
    else:
        forbidden_extra.append(SHAVE_LABEL)

    if quiet:
        forbidden_extra.extend([LAUNDRY_FOLD_LABEL, "laundry", "wash"])

    if events:
        scheduled.extend(reminders.trip_prep_tasks(events, morning))
        scheduled.extend(reminders.trip_pack_tasks(events, target))

    if SHAVE_LABEL in forbidden_extra:
        carry = [c for c in carry if not matches_word(c, SHAVE_PATTERNS)]
    if quiet:
        carry = [c for c in carry if not matches_word(c, LAUNDRY_ALL_PATTERNS)]
        cadence_labels = [c for c in cadence_labels if c != LAUNDRY_FOLD_LABEL]

    # Ollama being down must never cost a day's note: degrade to a template
    # note with reminders/tasks instead of aborting.
    ollama_ok = True
    try:
        wait_for_ollama()
    except SystemExit as e:
        ollama_ok = False
        print(f"{e}\nContinuing without the AI coach — note will use reminders/tasks only.")

    bill_tasks: list[str] = []
    try:
        mails, bill_tasks = reminders.load_gmail(target, args.model, OLLAMA_URL)
        # Only act on a bill once it's within the lead window (or overdue/undated);
        # a statement that arrived weeks early stays quiet until it's worth paying.
        n_bill_tasks = len(bill_tasks)
        bill_tasks = [b for b in bill_tasks if reminders.bill_is_due_soon(b, target)]
        if n_bill_tasks != len(bill_tasks):
            print(f"Bills: held {n_bill_tasks - len(bill_tasks)} not yet within the due window")
        if bill_tasks:
            scheduled.extend(bill_tasks)
            print("Bill tasks from email: " + ", ".join(bill_tasks[:3]))
    except Exception as e:  # noqa: BLE001
        print(f"Gmail fetch/triage failed ({e}); continuing without inbox.")

    msg_plans: list[str] = []
    msg_themes: list[str] = []
    try:
        msg_tasks, msg_plans, msg_themes = imessage.load_imessage(
            target, args.model, OLLAMA_URL
        )
        # A message lingers in the lookback window for days and the model rewords
        # the same commitment each run. Surface each commitment ONCE (carry-over
        # keeps it alive while unchecked); drop later near-duplicate re-extractions
        # via a grow-only signature store.
        if msg_tasks:
            seen_sigs = read_seen_msgtasks()
            fresh_msg_tasks: list[str] = []
            for t in msg_tasks:
                sig = taskcat.significant_words(t)
                if sig and any(taskcat.jaccard(sig, s) >= 0.5 for s in seen_sigs):
                    continue
                fresh_msg_tasks.append(t)
                if sig:
                    seen_sigs.append(sig)
            skipped = len(msg_tasks) - len(fresh_msg_tasks)
            if skipped:
                print(f"iMessage: skipped {skipped} already-surfaced commitment(s)")
            if not args.dry_run:
                write_seen_msgtasks(seen_sigs)
            scheduled.extend(fresh_msg_tasks)
        if msg_tasks or msg_plans or msg_themes:
            print(
                f"iMessage: {len(msg_tasks)} tasks, {len(msg_plans)} plans, "
                f"{len(msg_themes)} themes"
            )
    except Exception as e:  # noqa: BLE001
        print(f"iMessage read failed ({e}); continuing without messages.")

    # A fresh statement supersedes a stale carried-over copy of the same bill
    # (amount/due date may have changed, so text comparison can't catch it).
    fresh_bill_keys = {bill_key(b) for b in bill_tasks if bill_key(b)}
    if fresh_bill_keys:
        carry = [c for c in carry if bill_key(c) not in fresh_bill_keys]

    if scheduled:
        print("Smart rules added: " + ", ".join(scheduled))

    required = dedup_by_key(list(RECURRING_TASKS) + carry + cadence_labels + scheduled)
    # Cap FORBIDDEN: newest entries matter most, and an unbounded list bloats
    # the prompt toward context overflow.
    forbidden = list(dict.fromkeys(forbidden + forbidden_extra))[:40]

    external_context = ""
    if events or mails or journal_seeds:
        external_context = reminders.format_coach_context(
            events, mails, target, journal_seeds=journal_seeds
        )
    if msg_themes:
        external_context += (
            "\n\nMESSAGE THEMES (anonymized, context only — never turn into tasks):\n"
            + "\n".join(f"- {t}" for t in msg_themes)
        )

    # Yesterday's actual journal text → follow-up prompts; long carry-overs → nudges.
    yesterday_journal = extract_section(read_note(notes[0]), JOURNAL_HEADING).strip()[:1500]
    slipped = slipped_tasks(target)
    if slipped:
        print("Slipping: " + ", ".join(f"{t} ({n}d)" for t, n in slipped[:3]))

    plan: dict = {}
    if ollama_ok:
        print(f"Asking {args.model} for a structured plan…")
        try:
            plan = ask_coach(
                context,
                forbidden,
                required,
                args.model,
                external_context,
                yesterday_journal=yesterday_journal,
                slipped=slipped,
            )
        except SystemExit as e:
            print(f"{e}\nContinuing without the AI plan.")
    if not plan:
        plan = {
            "lookback": "(AI coach unavailable — note written without a generated plan)"
        }

    path = note_path_for(target)
    if path.exists():
        print(f"Updating existing note: {path.name}")
        note = path.read_text(encoding="utf-8")
    else:
        print(f"Creating new note from template: {path.name}")
        note = render_template(target)

    # Reminders: always replaced each run (calendar + inbox), like Looking back.
    # `ignored` honors the "ignore" notes the user left on past email lines.
    ignored = ignored_email_keys(target)
    receipt_lines: list[str] = []
    if RECEIPTS_ENABLED:
        recents = recent_receipts(target)
        receipt_lines = render_receipt_lines(recents)
        if recents:
            print(f"Receipts: {len(recents)} in the last {RECEIPTS_LOOKBACK_DAYS}d → surfaced")
    reminders_body = reminders.render_reminders_markdown(
        events, mails, target, extra_lines=msg_plans, ignored=ignored,
        receipt_lines=receipt_lines,
    )
    note = inject_section(note, REMINDERS_HEADING, reminders_body)

    focus_items = as_list(plan, "focus")
    # Pin today's Focus to the sprint's current deliverable so the morning's top
    # section always nudges the AI goal.
    sprint_focus = aijourney.focus_line(target)
    if sprint_focus:
        focus_items = [sprint_focus] + focus_items
    note = fill_if_empty(note, FOCUS_HEADING, focus_items)

    raw_groups = plan.get("task_groups", [])
    groups = raw_groups if isinstance(raw_groups, list) else []
    required_bills = [t for t in required if bill_key(t)]
    required_rest = [t for t in required if not bill_key(t)]
    # Drop bills the user already paid (checked off) for this billing cycle, so
    # a past-due statement that still sits in the inbox stops regenerating.
    paid = paid_bill_keys(target)
    n_bills = len(required_bills)
    required_bills = [b for b in required_bills if not is_paid_bill(b, target, paid)]
    if n_bills != len(required_bills):
        print(f"Bills: suppressed {n_bills - len(required_bills)} already-paid this cycle")

    # Deterministically (re)bucket the ENTIRE Tasks section every run. The coach's
    # bucket names are ignored — taskcat assigns a fixed category to each task so
    # the layout is identical day to day. Existing lines keep their checked state;
    # coach suggestions and REQUIRED tasks (recurring, carry-over, cadence, bills)
    # are merged in. `required` is the canonical wording, so a bill's fresh amount
    # overrides a stale carried copy (subsumes the old upsert/append paths).
    required_clean = required_rest + required_bills
    coach_tasks = [
        (str(it), False)
        for g in groups
        if isinstance(g, dict) and isinstance(g.get("items"), list)
        for it in g["items"]
    ]
    all_tasks = extract_task_states(note) + coach_tasks
    body_lines = taskcat.render_grouped(all_tasks, required_clean)
    if body_lines:
        note = replace_section_body(note, TASKS_HEADING, body_lines)

    # Remove paid bills that an earlier run already wrote into the note (upsert
    # only adds/updates; it never deletes). Checked-off lines are left intact.
    if paid:
        note = strip_unchecked_where(note, lambda t: is_paid_bill(t, target, paid))
    if SHAVE_LABEL in forbidden_extra:
        note = strip_unchecked_tasks(note, SHAVE_PATTERNS)
    if quiet:
        note = strip_unchecked_tasks(note, LAUNDRY_ALL_PATTERNS)
    # Pull out anything completed within the grace period (e.g. Influenster video).
    note = strip_unchecked_in_set(note, done_recent)
    # Backstop: remove any copied email/reminder lines that reached the Tasks list.
    note = strip_reminder_echoes(note)

    # AI Journey: deterministic streak + sprint week/deliverable (refreshed daily).
    note = inject_section(note, AIJOURNEY_HEADING, "\n".join(aijourney.journey_lines(target)))

    blog_items = as_list(plan, "blog_ideas")
    # On Sundays, seed a ready-to-edit build-in-public draft from the week's commits.
    if target.weekday() == 6:
        blog_items = aijourney.build_in_public_draft(target) + blog_items
    note = fill_if_empty(note, BLOG_HEADING, blog_items)
    note = fill_if_empty(note, WINS_HEADING, as_list(plan, "wins_prompts"))
    journal_items = as_list(plan, "journal_prompts")
    note = refresh_prompts(note, JOURNAL_HEADING, journal_items)
    note = refresh_prompts(note, TOMORROW_HEADING, as_list(plan, "tomorrow"))

    parts = [plan.get("lookback", "").strip() or "(no reflection)"]
    why = suppression_notes(target)
    if why:
        parts.append("**Why today's list differs:**\n" + "\n".join(f"- {w}" for w in why))
    done_recent = recent_completions(target)
    if done_recent:
        parts.append("**Recently completed:**\n" + "\n".join(f"- {d}" for d in done_recent))
    if slipped:
        parts.append(
            "**Slipping:**\n"
            + "\n".join(f'- "{t}" has carried over {n} days' for t, n in slipped[:3])
        )
    note = inject_section(note, LOOKBACK_HEADING, "\n\n".join(parts))

    if WEEKLY_ENABLED and (target.weekday() == 6 or args.weekly):
        weekly_body = ""
        try:
            print("Generating weekly reflection…")
            digest = weekly.build_week_digest(target)
            wplan = weekly.ask_weekly(digest, args.model, OLLAMA_URL)
            weekly_body = weekly.render_weekly(wplan)
        except Exception as e:  # noqa: BLE001
            print(f"Weekly reflection failed ({e}); using sprint summary only.")
        # Sprint progress is deterministic — always include it, even if the LLM
        # reflection failed.
        sprint = aijourney.weekly_progress(target)
        weekly_body = f"{weekly_body}\n\n{sprint}".strip() if weekly_body else sprint
        if weekly_body:
            note = inject_section(note, weekly.WEEKLY_HEADING, weekly_body)

    _print_run_summary(
        events=events,
        mails=mails,
        required=required,
        focus_items=focus_items,
        journal_items=journal_items,
        reminders_body=reminders_body,
    )

    if args.dry_run:
        print("\n" + "=" * 60 + "\n")
        print(note)
        return True

    path.write_text(note, encoding="utf-8")
    print(f"Wrote {path}")
    return True


def _write_stub_note(d: dt.date, dry_run: bool) -> None:
    """Backfill a missed day with a bare template note (no Ollama run)."""
    path = note_path_for(d)
    if path.exists():
        print(f"Backfill: {path.name} already exists; left untouched.")
        return
    if dry_run:
        print(f"Backfill (dry-run): would write stub note {path.name}")
        return
    path.write_text(render_template(d), encoding="utf-8")
    print(f"Backfill: wrote stub note {path.name}")


def _run_catch_up(today: dt.date, args: argparse.Namespace) -> None:
    missed = dates_to_backfill(today, read_last_run(), MAX_BACKFILL_DAYS)
    if not missed:
        print("Catch-up: today already processed; nothing to do.")
        ping_heartbeat(True)
        return
    print("Catch-up: processing " + ", ".join(d.isoformat() for d in missed))
    try:
        for d in missed:
            if d == today or BACKFILL_MODE == "full":
                if not run_for_date(d, args):
                    raise RuntimeError(f"run for {d} did not complete")
            else:
                _write_stub_note(d, args.dry_run)
            if not args.dry_run:
                write_last_run(d)
    except BaseException:
        if not args.dry_run:
            ping_heartbeat(False)
        raise
    if not args.dry_run:
        ping_heartbeat(True)


def main() -> None:
    args = parse_args()
    today = dt.date.fromisoformat(args.date) if args.date else dt.date.today()

    if args.check_imessage:
        raise SystemExit(0 if imessage.check_access() else 1)

    # Whatever happens, stop the Ollama instance we started (a user-started
    # server is left alone) so it doesn't sit in RAM between runs.
    try:
        if args.catch_up:
            _run_catch_up(today, args)
            return

        try:
            ok = run_for_date(today, args)
        except BaseException:
            if not args.dry_run:
                ping_heartbeat(False)
            raise
        if ok and not args.dry_run:
            write_last_run(today)
            ping_heartbeat(True)
    finally:
        shutdown_ollama()


def _print_run_summary(
    *,
    events: list[dict],
    mails: list[dict],
    required: list[str],
    focus_items: list[str],
    journal_items: list[str],
    reminders_body: str,
) -> None:
    """End-of-run checklist so you can see what actually fired."""
    print("\n--- Run summary ---")
    print(f"  Reminders: {len(events)} calendar events, {len(mails)} inbox items → injected")
    if "nothing pulled" in reminders_body:
        print("    (Google not connected or no data — see credentials.json)")
    print(f"  Smart/required tasks: {len(required)} total for coach + Tasks merge")
    print(f"  Focus prompts: {len(focus_items)}")
    print(f"  Journal prompts: {len(journal_items)}")
    print("  Looking back: refreshed")
    print("---")


if __name__ == "__main__":
    main()
