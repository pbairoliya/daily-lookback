"""Bills only surface within a lead window of their due date (or overdue/undated)."""
import datetime as dt

from reminders import bill_is_due_soon, is_trip_prep_task, parse_due_date

REF = dt.date(2026, 6, 18)


def test_parse_month_name() -> None:
    assert parse_due_date("due Jul 14", REF) == dt.date(2026, 7, 14)
    assert parse_due_date("Jul 14, 2027", REF) == dt.date(2027, 7, 14)
    assert parse_due_date("Sept 3", REF) == dt.date(2026, 9, 3)


def test_parse_numeric() -> None:
    assert parse_due_date("7/14", REF) == dt.date(2026, 7, 14)
    assert parse_due_date("7/14/27", REF) == dt.date(2027, 7, 14)


def test_parse_year_rollover_when_omitted() -> None:
    dec = dt.date(2026, 12, 20)
    assert parse_due_date("Jan 5", dec) == dt.date(2027, 1, 5)  # nearest future
    jan = dt.date(2026, 1, 10)
    assert parse_due_date("Dec 28", jan) == dt.date(2025, 12, 28)  # nearest past


def test_parse_unparseable() -> None:
    assert parse_due_date("", REF) is None
    assert parse_due_date("amount in email", REF) is None


def test_far_future_bill_held() -> None:
    # due Jul 14, today Jun 18 → 26 days out, lead 4 → hidden
    assert bill_is_due_soon("Pay card — Amex ($500, due Jul 14)", REF, lead_days=4) is False


def test_within_window_shown() -> None:
    # due Jun 21, today Jun 18 → 3 days out, lead 4 → shown
    assert bill_is_due_soon("due Jun 21", REF, lead_days=4) is True
    # exactly on the boundary (4 days) → shown
    assert bill_is_due_soon("due Jun 22", REF, lead_days=4) is True


def test_overdue_shown() -> None:
    assert bill_is_due_soon("due Jun 10", REF, lead_days=4) is True


def test_undated_bill_shown() -> None:
    # No parseable due date → be safe, show it.
    assert bill_is_due_soon("Pay credit card — Amex: statement ready", REF) is True


def test_lead_window_example_from_user() -> None:
    # User's spec: bill due Jul 14 → start showing Jul 10 onward.
    due = "due Jul 14"
    assert bill_is_due_soon(due, dt.date(2026, 7, 9), lead_days=4) is False
    assert bill_is_due_soon(due, dt.date(2026, 7, 10), lead_days=4) is True


# --- trip prep carry filter ----------------------------------------------

def test_trip_prep_detected() -> None:
    assert is_trip_prep_task("Prep / pack for tomorrow: Flight to Boston")
    assert is_trip_prep_task("Start packing list for Boston trip (in 2 days)")


def test_non_trip_task_not_flagged() -> None:
    assert not is_trip_prep_task("Pay credit card — Amex")
    assert not is_trip_prep_task("Finish RAG chatbot")
