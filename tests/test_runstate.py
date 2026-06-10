"""Catch-up planning: which dates need a run."""
import datetime as dt

from runstate import dates_to_backfill

TODAY = dt.date(2026, 6, 9)


def test_no_history_means_today_only() -> None:
    assert dates_to_backfill(TODAY, None) == [TODAY]


def test_already_ran_today() -> None:
    assert dates_to_backfill(TODAY, TODAY) == []
    assert dates_to_backfill(TODAY, TODAY + dt.timedelta(days=1)) == []


def test_ran_yesterday() -> None:
    assert dates_to_backfill(TODAY, TODAY - dt.timedelta(days=1)) == [TODAY]


def test_missed_three_days() -> None:
    last = TODAY - dt.timedelta(days=4)
    assert dates_to_backfill(TODAY, last) == [
        dt.date(2026, 6, 6),
        dt.date(2026, 6, 7),
        dt.date(2026, 6, 8),
        TODAY,
    ]


def test_backfill_window_is_capped() -> None:
    last = TODAY - dt.timedelta(days=30)
    out = dates_to_backfill(TODAY, last, max_days=7)
    assert len(out) == 7
    assert out[-1] == TODAY
    assert out[0] == TODAY - dt.timedelta(days=6)
