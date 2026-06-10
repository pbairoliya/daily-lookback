"""Identity-key behavior: what counts as 'the same task'."""
import pytest

from taskkeys import bill_key, dedup_by_key, is_payment_task, task_key


@pytest.mark.parametrize(
    ("a", "b"),
    [
        # The reported bug: same bill, new statement amount/due date.
        (
            "Pay rent — Bozzuto ($2,450, due 06/01)",
            "Pay rent — Bozzuto ($2,500, due 07/01)",
        ),
        (
            "Pay credit card — Chase ($1,900, due 2026-06-14)",
            "Pay credit card — Chase ($2,000, due 2026-07-15)",
        ),
        # Punctuation / case / whitespace drift (coach rewording).
        ("Email John re: contract", "email john  re contract!"),
        ("Call dentist.", "Call dentist"),
        # Trailing parenthetical detail.
        ("Grocery run (Costco / BJ's / store)", "Grocery run"),
        # Date phrasing variants.
        ("Renew passport by June 15", "Renew passport"),
        ("Submit report due Friday", "Submit report"),
    ],
)
def test_same_task_same_key(a: str, b: str) -> None:
    assert task_key(a) == task_key(b)


@pytest.mark.parametrize(
    ("a", "b"),
    [
        # Bare numbers must survive — these are different tasks.
        ("Read ch. 3", "Read ch. 4"),
        ("Pay rent — Bozzuto", "Pay credit card — Chase"),
        ("Call dentist", "Call mom"),
    ],
)
def test_different_task_different_key(a: str, b: str) -> None:
    assert task_key(a) != task_key(b)


def test_bill_key_ignores_subject_tail() -> None:
    a = "Pay bill — Comcast: Your statement is ready"
    b = "Pay bill — Comcast: Action required - payment due soon"
    assert bill_key(a) == bill_key(b) == "pay bill comcast"


def test_bill_key_none_for_non_payment() -> None:
    assert bill_key("Email John re: contract") is None
    assert bill_key("Fold and put away laundry") is None


def test_is_payment_task() -> None:
    assert is_payment_task("Pay rent — Bozzuto ($2,450, due 06/01)")
    assert is_payment_task("Pay apartment rent / building bill")
    assert not is_payment_task("Prepare invoice for client")


def test_dedup_by_key_keeps_first_text() -> None:
    items = [
        "Pay rent — Bozzuto ($2,500, due 07/01)",
        "Pay rent — Bozzuto ($2,450, due 06/01)",
        "Call dentist",
        "call dentist!",
    ]
    assert dedup_by_key(items) == [
        "Pay rent — Bozzuto ($2,500, due 07/01)",
        "Call dentist",
    ]
