"""AI-journey tracker: learning streak + sprint schedule mapping."""
import datetime as dt

import pytest

import aijourney
import vault

TODAY = dt.date(2026, 7, 1)  # a Wednesday, inside Week 2 of the default sprint
AI = "🤖 AI learning (1–1.5h)"
INTERVIEW = "🧮 Interview prep (LeetCode / system design)"


def _note(done: list[str] = (), open_: list[str] = ()) -> str:
    lines = ["# note", "", "## ✅ Tasks", ""]
    lines += [f"- [x] {t}" for t in done]
    lines += [f"- [ ] {t}" for t in open_]
    return "\n".join(lines) + "\n"


@pytest.fixture
def fake_vault(tmp_path, monkeypatch):
    monkeypatch.setattr(vault, "DAILY_DIR", tmp_path)
    monkeypatch.delenv("AI_SPRINT_START", raising=False)
    # Isolate from real ~/ai-engineering git history so streak tests are stable.
    monkeypatch.setattr(aijourney, "AI_REPOS_DIR", tmp_path / "norepos")
    return tmp_path


def _write(vault_dir, day: dt.date, **kw) -> None:
    (vault_dir / f"{day.isoformat()}.md").write_text(_note(**kw))


# --- streak ---------------------------------------------------------------

def test_streak_counts_consecutive_checked_days(fake_vault) -> None:
    for i in range(1, 5):  # yesterday back 4 days, all ticked
        _write(fake_vault, TODAY - dt.timedelta(days=i), done=[AI])
    assert aijourney.learning_streak(TODAY) == 4


def test_unticked_day_breaks_streak(fake_vault) -> None:
    _write(fake_vault, TODAY - dt.timedelta(days=1), done=[AI])
    _write(fake_vault, TODAY - dt.timedelta(days=2), open_=[AI])  # skipped
    _write(fake_vault, TODAY - dt.timedelta(days=3), done=[AI])
    assert aijourney.learning_streak(TODAY) == 1


def test_missing_note_breaks_streak(fake_vault) -> None:
    _write(fake_vault, TODAY - dt.timedelta(days=1), done=[AI])
    # gap at day 2
    _write(fake_vault, TODAY - dt.timedelta(days=3), done=[AI])
    assert aijourney.learning_streak(TODAY) == 1


def test_today_done_shows_incremented_streak(fake_vault) -> None:
    for i in range(1, 4):
        _write(fake_vault, TODAY - dt.timedelta(days=i), done=[AI])
    _write(fake_vault, TODAY, done=[AI])
    line = aijourney.journey_lines(TODAY)[0]
    assert "logged today" in line and "4-day streak" in line


def test_days_since_last_learn(fake_vault) -> None:
    _write(fake_vault, TODAY - dt.timedelta(days=3), done=[AI])
    assert aijourney.days_since_last_learn(TODAY) == 3


def test_no_history_no_streak(fake_vault) -> None:
    assert aijourney.learning_streak(TODAY) == 0
    assert aijourney.days_since_last_learn(TODAY) is None
    assert "No streak yet" in aijourney.journey_lines(TODAY)[0]


# --- interview pace -------------------------------------------------------

def test_interview_sessions_counts_from_monday(fake_vault) -> None:
    monday = TODAY - dt.timedelta(days=TODAY.weekday())
    _write(fake_vault, monday, done=[INTERVIEW])
    _write(fake_vault, monday + dt.timedelta(days=1), done=[INTERVIEW])
    _write(fake_vault, monday - dt.timedelta(days=1), done=[INTERVIEW])  # last week
    assert aijourney.interview_sessions_this_week(TODAY) == 2


# --- schedule mapping -----------------------------------------------------

def test_week_number_before_start_is_none(fake_vault) -> None:
    before = aijourney.plan_start() - dt.timedelta(days=2)
    assert aijourney.week_number(before) is None
    assert "Sprint starts" in " ".join(aijourney.journey_lines(before))


def test_week_number_and_phase(fake_vault) -> None:
    start = aijourney.plan_start()
    assert aijourney.week_number(start) == 1
    assert aijourney.week_number(start + dt.timedelta(days=7)) == 2
    assert aijourney.week_number(start + dt.timedelta(weeks=8)) == 9
    assert aijourney.phase_for(1) == "Deep Learning & PyTorch fluency"
    assert aijourney.phase_for(9) == "MLOps & Cloud deployment"


def test_journey_lines_show_week_and_deliverable(fake_vault) -> None:
    text = " ".join(aijourney.journey_lines(TODAY))
    assert "Week 2/16" in text
    assert aijourney.WEEK_PLAN[2] in text


def test_start_date_env_override(fake_vault, monkeypatch) -> None:
    monkeypatch.setenv("AI_SPRINT_START", "2026-08-03")
    assert aijourney.plan_start() == dt.date(2026, 8, 3)


# --- git-commit streak ----------------------------------------------------

def test_commit_counts_toward_streak(fake_vault) -> None:
    commits = {TODAY - dt.timedelta(days=i) for i in (1, 2, 3)}
    assert aijourney.learning_streak(TODAY, commits=commits) == 3


def test_box_or_commit_either_counts(fake_vault) -> None:
    # yesterday via box, day-2 via commit, day-3 nothing → streak 2
    _write(fake_vault, TODAY - dt.timedelta(days=1), done=[AI])
    commits = {TODAY - dt.timedelta(days=2)}
    assert aijourney.learning_streak(TODAY, commits=commits) == 2


def test_today_commit_shows_in_journey(fake_vault, monkeypatch) -> None:
    monkeypatch.setattr(aijourney, "commit_dates", lambda today, **k: {TODAY})
    line = aijourney.journey_lines(TODAY)[0]
    assert "commit detected" in line


# --- sprint Focus / weekly / blog ----------------------------------------

def test_focus_line_during_sprint(fake_vault) -> None:
    assert aijourney.focus_line(TODAY) == f"🤖 Sprint Wk 2: {aijourney.WEEK_PLAN[2]}"


def test_focus_line_none_before_start(fake_vault) -> None:
    assert aijourney.focus_line(aijourney.plan_start() - dt.timedelta(days=2)) is None


def test_weekly_progress_has_week_and_next(fake_vault) -> None:
    out = aijourney.weekly_progress(TODAY)
    assert "Week 2/16" in out
    assert aijourney.WEEK_PLAN[3] in out  # next week


def test_build_in_public_draft(fake_vault, monkeypatch) -> None:
    monkeypatch.setattr(aijourney, "commit_log", lambda today, **k: ["daily-lookback: add taskcat"])
    out = aijourney.build_in_public_draft(TODAY)
    assert out and "Build-in-public" in out[0]
    assert "add taskcat" in out[0]


def test_build_in_public_empty_without_commits(fake_vault, monkeypatch) -> None:
    monkeypatch.setattr(aijourney, "commit_log", lambda today, **k: [])
    assert aijourney.build_in_public_draft(TODAY) == []
