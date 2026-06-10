"""Merge behavior in ## Tasks: append dedup by key, bill upsert in place."""
from note_io import append_tasks, tasks_missing_from_note, upsert_tasks

NOTE = """# 2026-06-09

## ✅ Tasks

**💸 Bills & Payments**
- [ ] Pay rent — Bozzuto ($2,450, due 06/01)
- [x] Pay credit card — Amex ($310, due 06/05)

**Home**
- [ ] Fold and put away laundry
- [ ] Email John re: contract

## 🪞 Looking back

(nothing yet)
"""


def test_append_blocks_exact_and_near_duplicates() -> None:
    out = append_tasks(
        NOTE,
        [
            "Email John re: contract",          # exact
            "email john re contract!",          # reworded
            "Pay rent — Bozzuto ($2,500, due 07/01)",  # stale-bill variant
            "Call dentist",                     # genuinely new
        ],
    )
    assert out.count("Email John") == 1
    assert out.count("Pay rent") == 1
    assert "- [ ] Call dentist" in out


def test_upsert_rewrites_stale_bill_in_place() -> None:
    out = upsert_tasks(NOTE, ["Pay rent — Bozzuto ($2,500, due 07/01)"])
    assert "- [ ] Pay rent — Bozzuto ($2,500, due 07/01)" in out
    assert "$2,450" not in out
    assert out.count("Pay rent") == 1
    # Position preserved: still inside the bills bucket, before Home.
    assert out.index("Pay rent") < out.index("**Home**")


def test_upsert_skips_checked_bill() -> None:
    out = upsert_tasks(NOTE, ["Pay credit card — Amex ($999, due 07/05)"])
    assert out == NOTE  # already paid → untouched


def test_upsert_appends_new_bill() -> None:
    out = upsert_tasks(NOTE, ["Pay bill — Comcast ($80, due 06/20)"])
    assert "- [ ] Pay bill — Comcast ($80, due 06/20)" in out


def test_upsert_handles_one_variant_per_bill_per_call() -> None:
    out = upsert_tasks(
        NOTE,
        [
            "Pay rent — Bozzuto ($2,500, due 07/01)",
            "Pay rent — Bozzuto: Your statement is ready",
        ],
    )
    assert out.count("Pay rent") == 1
    assert "$2,500" in out


def test_missing_compares_by_key() -> None:
    missing = tasks_missing_from_note(
        NOTE, ["EMAIL JOHN RE CONTRACT", "Fold and put away laundry", "Call mom"]
    )
    assert missing == ["Call mom"]


def test_idempotent_double_merge() -> None:
    tasks = ["Call dentist", "Pay bill — Comcast ($80, due 06/20)"]
    once = upsert_tasks(append_tasks(NOTE, ["Call dentist"]), ["Pay bill — Comcast ($80, due 06/20)"])
    twice = upsert_tasks(append_tasks(once, ["Call dentist"]), ["Pay bill — Comcast ($80, due 06/20)"])
    assert once == twice
    assert all(once.count(t.split(" — ")[0]) >= 1 for t in tasks)
