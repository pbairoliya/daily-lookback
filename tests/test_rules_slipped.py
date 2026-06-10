"""Accountability nudges: consecutive-day carry-over streaks."""
import datetime as dt

import pytest

import vault
from rules import slipped_tasks, task_ages

TODAY = dt.date(2026, 6, 9)


def _note(tasks_open: list[str], tasks_done: list[str] = ()) -> str:
    lines = ["# note", "", "## ✅ Tasks", ""]
    lines += [f"- [ ] {t}" for t in tasks_open]
    lines += [f"- [x] {t}" for t in tasks_done]
    return "\n".join(lines) + "\n"


@pytest.fixture
def fake_vault(tmp_path, monkeypatch):
    monkeypatch.setattr(vault, "DAILY_DIR", tmp_path)
    return tmp_path


def test_streak_counts_consecutive_days(fake_vault) -> None:
    for i in range(1, 5):  # yesterday back 4 days
        d = TODAY - dt.timedelta(days=i)
        open_tasks = ["Call dentist"]
        if i <= 2:
            open_tasks.append("Email John re: contract")
        (fake_vault / f"{d.isoformat()}.md").write_text(_note(open_tasks))
    ages = dict(task_ages(TODAY))
    assert ages["Call dentist"] == 4
    assert ages["Email John re: contract"] == 2


def test_slipped_threshold(fake_vault) -> None:
    for i in range(1, 6):
        d = TODAY - dt.timedelta(days=i)
        (fake_vault / f"{d.isoformat()}.md").write_text(_note(["Call dentist", "New thing"] if i == 1 else ["Call dentist"]))
    slipped = slipped_tasks(TODAY, k=3)
    assert slipped == [("Call dentist", 5)]


def test_reworded_task_still_counts_as_one_streak(fake_vault) -> None:
    texts = ["Call the dentist!", "call the dentist", "Call the dentist"]
    for i, t in enumerate(texts, start=1):
        d = TODAY - dt.timedelta(days=i)
        (fake_vault / f"{d.isoformat()}.md").write_text(_note([t]))
    ages = task_ages(TODAY)
    assert ages == [("Call the dentist!", 3)]  # yesterday's text, full streak


def test_missing_note_breaks_streak(fake_vault) -> None:
    for i in (1, 2, 4):  # gap at day 3
        d = TODAY - dt.timedelta(days=i)
        (fake_vault / f"{d.isoformat()}.md").write_text(_note(["Call dentist"]))
    assert dict(task_ages(TODAY))["Call dentist"] == 2


def test_no_yesterday_note_means_no_streaks(fake_vault) -> None:
    assert task_ages(TODAY) == []
