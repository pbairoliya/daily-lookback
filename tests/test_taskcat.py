"""Deterministic task categorization + grouped rendering."""
import taskcat
from taskcat import categorize, render_grouped


def test_categories_are_stable_and_correct() -> None:
    cases = {
        "Workout": "health",
        "Start working out": "health",
        "Yoga": "health",
        "Shave": "health",
        "Shower": "health",
        "Work": "work",
        "Cook at least one meal": "home",
        "Make Marimi tofu": "home",
        "Study for 1 hour": "ai",
        "🤖 AI learning (1–1.5h)": "ai",
        "🧮 Interview prep (LeetCode / system design)": "ai",
        "Finish Modules 2-5 for AI math please": "ai",
        "Explore Obsidian vault syncing with iCloud": "ai",
        "Refine the daily-lookback v1 structure": "ai",
        "Transfer $25k to 5/3": "money",
        "Call 5/3 about the bank account": "money",
        "Review Merrill Edge statement": "money",
        "Make an oil change appointment": "money",
        "Pick up Alex's shoes tomorrow": "people",
        "Consider recent safety alerts": "other",
        "Grocery run (Costco / BJ's / store)": "home",
        "Respond to Alex about lunch with Jordan in DC": "people",
        "Make breakfast at home pls": "home",
        "Make a physical appointment": "health",
    }
    for task, expected in cases.items():
        assert categorize(task) == expected, f"{task!r} -> {categorize(task)} (want {expected})"


def test_payments_bucket_first_and_separate() -> None:
    tasks = [
        ("Pay credit card — Discover …6225 ($765.46, due Jul 14)", False),
        ("Workout", False),
    ]
    out = render_grouped(tasks)
    assert out[0] == "**💸 Bills & Payments**"
    assert out[1].startswith("- [ ] Pay credit card")


def test_checked_state_preserved() -> None:
    out = render_grouped([("Review Merrill Edge statement", True)])
    assert any(line == "- [x] Review Merrill Edge statement" for line in out)


def test_dedup_by_key_merges_checked() -> None:
    # Same task once unchecked, once checked → one line, checked wins.
    out = render_grouped([("Workout", False), ("workout", True)])
    workout_lines = [l for l in out if "orkout" in l]
    assert workout_lines == ["- [x] Workout"]


def test_required_forced_in_and_canonical() -> None:
    # A required bill with a fresh amount overrides a stale carried copy.
    stale = "Pay credit card — Amex …1111 ($200.00, due Jul 12)"
    fresh = "Pay credit card — Amex …1111 ($214.69, min $35.00, due Jul 12)"
    out = render_grouped([(stale, False)], required=[fresh])
    pay_lines = [l for l in out if l.startswith("- [")]
    assert any("214.69" in l for l in pay_lines)
    assert not any("800.00" in l for l in pay_lines)


def test_noise_task_dropped() -> None:
    out = render_grouped([("🛒 shoes — mentioned in journal", True)])
    assert out == []  # nothing but a noise item → empty body


def test_display_order_bills_then_work_then_ai() -> None:
    tasks = [
        ("Work", False),
        ("Study for 1 hour", False),
        ("Pay rent — ($2000, due Jul 1)", False),
    ]
    out = render_grouped(tasks)
    headings = [l for l in out if l.startswith("**")]
    assert headings[0] == "**💸 Bills & Payments**"
    assert headings.index("**💼 Work**") < headings.index("**🤖 AI & Learning**")


def test_other_bucket_last() -> None:
    out = render_grouped([("Consider recent safety alerts", False), ("Work", False)])
    headings = [l for l in out if l.startswith("**")]
    assert headings[-1] == "**📥 Other**"


def test_done_redo_collapses() -> None:
    # A done task absorbs an unchecked near-duplicate re-extracted from messages.
    out = render_grouped([
        ("Check tracking for Alex's order.", True),
        ("Check tracking for an order Alex placed.", False),
    ])
    tracking = [l for l in out if "tracking" in l.lower()]
    assert tracking == ["- [x] Check tracking for Alex's order."]


def test_distinct_active_tasks_not_collapsed() -> None:
    # Two different unchecked tasks must both survive (only done-vs-undone merges).
    out = render_grouped([
        ("Refine the daily-lookback v1 structure", False),
        ("Explore Obsidian vault syncing with iCloud", False),
    ])
    assert sum(1 for l in out if l.startswith("- [ ]")) == 2


def test_display_keys_all_valid() -> None:
    valid = {k for k, _, _ in taskcat.CATEGORIES}
    assert set(taskcat.DISPLAY_ORDER) <= valid
