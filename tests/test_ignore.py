"""The 'ignore' convention + Looking-back completion trimming."""
import datetime as dt

import pytest

import runstate
import vault
from note_io import REMINDERS_HEADING
from rules import (
    ignore_stem,
    ignored_email_keys,
    is_ignored_mail,
    recent_completions,
)

TODAY = dt.date(2026, 6, 15)


@pytest.fixture
def fake_env(tmp_path, monkeypatch):
    """Isolated vault + persistent-state dir so tests never touch real files."""
    monkeypatch.setattr(vault, "DAILY_DIR", tmp_path)
    monkeypatch.setattr(runstate, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(runstate, "IGNORED_FILE", tmp_path / "state" / "ignored.json")
    return tmp_path


def _reminders_note(lines: list[str]) -> str:
    return f"# note\n\n## {REMINDERS_HEADING}\n\n" + "\n".join(lines) + "\n"


def test_ignore_stem_strips_dates_and_digits() -> None:
    a = ignore_stem("🎁 6 boxes has been sent to you on Jun 14, 2026.")
    b = ignore_stem("8 boxes has been sent to you on Jun 20, 2026.")
    assert a == b == "boxes has been sent to you on"


def test_is_ignored_mail_matches_templated_subject_same_sender() -> None:
    keys = {("temu", "boxes has been sent to you on")}
    assert is_ignored_mail(
        {"from": "Temu <deals@temu.com>", "subject": "9 boxes has been sent to you on Jul 1, 2026."},
        keys,
    )
    # Different sender, same subject shape → not suppressed.
    assert not is_ignored_mail(
        {"from": "Amazon", "subject": "3 boxes has been sent to you on Jul 1"}, keys
    )


def test_per_line_granularity(fake_env) -> None:
    note = _reminders_note([
        '- [x] **The Point at McLean** [FYI] — "The Point at McLean - Service Request Complete" — done. Ignore',
        '- [x] **The Point at McLean** [FYI] — "The Point at McLean - Service Request Status Update" — fyi.',
    ])
    (fake_env / f"{TODAY.isoformat()}.md").write_text(note)
    keys = ignored_email_keys(TODAY)
    assert is_ignored_mail(
        {"from": "The Point at McLean", "subject": "The Point at McLean - Service Request Complete"}, keys
    )
    # The sibling line the user did NOT mark stays visible.
    assert not is_ignored_mail(
        {"from": "The Point at McLean", "subject": "The Point at McLean - Service Request Status Update"}, keys
    )


def test_ignore_persists_after_note_regenerated(fake_env) -> None:
    note = _reminders_note([
        '- [x] **Google** [Decision] — "Sign in to your Google Account" — security. Ignore',
    ])
    path = fake_env / f"{TODAY.isoformat()}.md"
    path.write_text(note)
    assert ("google", "sign in to your google account") in ignored_email_keys(TODAY)

    # Simulate the nightly regeneration erasing the annotated line.
    path.write_text(_reminders_note(["- [ ] something else"]))
    # The ignore survives because it was persisted to the store.
    assert ("google", "sign in to your google account") in ignored_email_keys(TODAY)


def _tasks_note(done: list[str]) -> str:
    return "# note\n\n## ✅ Tasks\n\n" + "\n".join(f"- [x] {t}" for t in done) + "\n"


def test_recent_completions_trims_older_days(fake_env) -> None:
    # 1 day ago: 4 done; 2 days ago: 4 done; 3 days ago: 4 done.
    for age in (1, 2, 3):
        d = TODAY - dt.timedelta(days=age)
        (fake_env / f"{d.isoformat()}.md").write_text(
            _tasks_note([f"Task {age}-{i}" for i in range(4)])
        )
    out = recent_completions(TODAY, days=3, cap=6)
    # Capped, and older days contribute progressively fewer items.
    assert len(out) <= 6
    assert sum(1 for x in out if "Jun 14" in x) == 3   # yesterday (age 1) → 3 kept
    assert sum(1 for x in out if "Jun 13" in x) == 2   # age 2 → 2 kept
    assert sum(1 for x in out if "Jun 12" in x) == 1   # age 3 → 1 kept


def test_recent_completions_dedupes(fake_env) -> None:
    for age in (1, 2):
        d = TODAY - dt.timedelta(days=age)
        (fake_env / f"{d.isoformat()}.md").write_text(_tasks_note(["Record video"]))
    out = recent_completions(TODAY, days=3)
    assert sum("Record video" in x for x in out) == 1  # newest occurrence only
