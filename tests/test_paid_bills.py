"""Paid bills don't regenerate; next cycle still shows."""
import datetime as dt

import pytest

import runstate
import vault
from rules import (
    bill_cycle_month,
    bill_payee_core,
    is_paid_bill,
    paid_bill_keys,
)

TODAY = dt.date(2026, 6, 15)


@pytest.fixture
def fake_env(tmp_path, monkeypatch):
    monkeypatch.setattr(vault, "DAILY_DIR", tmp_path)
    monkeypatch.setattr(runstate, "STATE_DIR", tmp_path / "s")
    monkeypatch.setattr(runstate, "PAID_BILLS_FILE", tmp_path / "s" / "paid_bills.json")
    return tmp_path


def _tasks_note(open_=(), done=()):
    body = ["# n", "", "## ✅ Tasks", ""]
    body += [f"- [ ] {t}" for t in open_]
    body += [f"- [x] {t}" for t in done]
    return "\n".join(body) + "\n"


def test_payee_core_drops_card_digits():
    assert bill_payee_core("Pay credit card — Bank of America …2222 ($2,500, due Jun 12)") == "bank of america"
    assert bill_payee_core("Pay credit card — Amex: Your June 2026 Statement is Ready") == "amex"
    assert bill_payee_core("Buy milk") is None


def test_cycle_from_due_date_else_ref():
    assert bill_cycle_month("Pay rent — X (due 06/01/2026)", TODAY) == "2026-06"
    assert bill_cycle_month("Pay credit card — Y (due July 12, 2026)", TODAY) == "2026-07"
    assert bill_cycle_month("Pay credit card — Z: statement available", dt.date(2026, 6, 14)) == "2026-06"


def test_paid_bill_suppressed_same_cycle_only(fake_env):
    # Yesterday's note has the BoA card checked off (paid), no due date in text.
    (fake_env / "2026-06-14.md").write_text(
        _tasks_note(done=["Pay credit card — Bank of America: statement available"])
    )
    keys = paid_bill_keys(TODAY)
    # Today's regenerated BoA statement for the SAME (June) cycle → suppressed.
    assert is_paid_bill("Pay credit card — Bank of America …2222 ($2,500, due June 12, 2026)", TODAY, keys)
    # Next month's BoA statement → different cycle → still shows.
    assert not is_paid_bill("Pay credit card — Bank of America …2222 ($2,400, due July 12, 2026)", TODAY, keys)
    # A different, unpaid payee → shows.
    assert not is_paid_bill("Pay credit card — Chase …4532: statement available", TODAY, keys)


def test_strip_removes_paid_bill_already_in_note(fake_env):
    from note_io import strip_unchecked_where

    (fake_env / "2026-06-14.md").write_text(
        _tasks_note(done=["Pay credit card — Bank of America: statement available"])
    )
    keys = paid_bill_keys(TODAY)
    note = _tasks_note(open_=[
        "Pay credit card — Bank of America …2222 ($2,500, due June 12, 2026)",  # paid
        "Pay credit card — Chase …4532: statement available",                   # unpaid
        "Buy milk",
    ])
    out = strip_unchecked_where(note, lambda t: is_paid_bill(t, TODAY, keys))
    assert "Bank of America …2222" not in out      # removed
    assert "Chase …4532" in out                    # kept
    assert "Buy milk" in out                        # kept


def test_strip_leaves_checked_paid_bill(fake_env):
    from note_io import strip_unchecked_where

    (fake_env / "2026-06-14.md").write_text(
        _tasks_note(done=["Pay rent — The Point at McLean (due 06/01/2026)"])
    )
    keys = paid_bill_keys(TODAY)
    note = _tasks_note(done=["Pay rent — The Point at McLean ($3,132, due 06/01/2026)"])
    # A checked line is history — never stripped.
    assert "The Point at McLean" in strip_unchecked_where(note, lambda t: is_paid_bill(t, TODAY, keys))


def test_paid_state_persists_across_regeneration(fake_env):
    (fake_env / "2026-06-14.md").write_text(
        _tasks_note(done=["Pay rent — The Point at McLean ($3,132, due 06/01/2026)"])
    )
    assert ("the point at mclean", "2026-06") in paid_bill_keys(TODAY)
    # Even after that note loses the checkmark, the store remembers.
    (fake_env / "2026-06-14.md").write_text(_tasks_note(open_=["something else"]))
    assert ("the point at mclean", "2026-06") in paid_bill_keys(TODAY)
