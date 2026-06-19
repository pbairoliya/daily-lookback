"""End-to-end run_for_date with the network + LLM stubbed — locks the whole
assembly pipeline (regroup, tomorrow→tasks, AI Journey, sections) without Ollama
or Google."""
import argparse
import datetime as dt

import aijourney
import coach
import config
import imessage
import lookback
import note_io
import reminders
import runstate
import vault

TARGET = dt.date(2026, 6, 19)  # a Friday (no weekly section)

_TEMPLATE = """---
type: daily
date: {{date:YYYY-MM-DD}}
---

# {{date:dddd, MMMM D, YYYY}}

## 🎯 Today's Focus
-

## ✅ Tasks
- [ ] Shower
- [ ] Work
- [ ] 🤖 AI learning (1–1.5h)
- [ ] 🧮 Interview prep (LeetCode / system design)
- [ ] Cook at least one meal
- [ ]

## 🤖 AI Journey
-

## 🧠 Learnings
-

## ✍️ Blog Ideas / Drafts
-

## 🏆 Wins & Gratitude
-

## 📓 Journal
-

## 🔜 Tomorrow
-
"""

_PLAN = {
    "focus": ["Ship the classifier"],
    "task_groups": [{"group": "whatever-the-model-called-it",
                     "items": ["Workout", "Study for 1 hour", "Review Merrill statement"]}],
    "blog_ideas": ["Why top-down DL"],
    "wins_prompts": ["What went well?"],
    "journal_prompts": ["How did today go?"],
    "tomorrow": ["Prep lesson 2"],
    "lookback": "Solid first day.",
}


def test_run_for_date_end_to_end(tmp_path, monkeypatch):
    daily = tmp_path / "Daily"
    daily.mkdir()
    template = tmp_path / "template.md"
    template.write_text(_TEMPLATE)

    # Redirect every DAILY_DIR / template / state / repo reference into tmp.
    monkeypatch.setattr(vault, "DAILY_DIR", daily)
    monkeypatch.setattr(note_io, "DAILY_DIR", daily)
    monkeypatch.setattr(note_io, "TEMPLATE_PATH", template)
    monkeypatch.setattr(aijourney, "AI_REPOS_DIR", tmp_path / "norepos")
    monkeypatch.setattr(runstate, "IGNORED_FILE", tmp_path / "ignored.json")
    monkeypatch.setattr(runstate, "PAID_BILLS_FILE", tmp_path / "paid.json")
    monkeypatch.setattr(runstate, "SEEN_MSGTASKS_FILE", tmp_path / "seen.json")
    monkeypatch.setattr(lookback, "RECEIPTS_ENABLED", False)
    monkeypatch.setattr(lookback, "WEEKLY_ENABLED", False)

    # Prior day's note: a carry-over task + a Tomorrow note that should become a task.
    (daily / "2026-06-18.md").write_text(
        "# prior\n\n## ✅ Tasks\n- [ ] Old carryover task\n\n"
        "## 🔜 Tomorrow\n- Call the leasing office\n"
    )

    # Stub all I/O + the LLM.
    monkeypatch.setattr(lookback, "wait_for_ollama", lambda *a, **k: None)
    monkeypatch.setattr(lookback, "ask_coach", lambda *a, **k: dict(_PLAN))
    monkeypatch.setattr(reminders, "load_calendar", lambda *a, **k: ([], []))
    monkeypatch.setattr(reminders, "load_gmail", lambda *a, **k: ([], []))
    monkeypatch.setattr(imessage, "load_imessage", lambda *a, **k: ([], [], []))

    args = argparse.Namespace(date=TARGET.isoformat(), days=5, model="test",
                              dry_run=False, weekly=False)
    assert lookback.run_for_date(TARGET, args) is True

    note = (daily / f"{TARGET.isoformat()}.md").read_text()

    # Deterministic buckets, not the model's invented names.
    assert "**🤖 AI & Learning**" in note   # Study / AI learning / Interview prep
    assert "**🧍 Health & Body**" in note    # Workout / Shower
    assert "**💼 Work**" in note
    assert "whatever-the-model-called-it" not in note
    # Tomorrow note became a task; carry-over preserved.
    assert "Call the leasing office" in note
    assert "Old carryover task" in note
    # New sections present.
    assert "## 🤖 AI Journey" in note
    assert "Ship the classifier" in note     # coach focus landed
