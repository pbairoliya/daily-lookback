"""Bill/statement classification + amount extraction.

Anchored to REAL email snippets that previously misfired: deposit-account and
"no payment required" notices were tagged as payable card bills, and two cards
from one issuer collapsed into a single line with no amount.
"""
from __future__ import annotations

import reminders as R

# --- Real snippets (verbatim shape from Gmail) -----------------------------

BOA_SAFEBALANCE = {
    "from": "onlinebanking@ealerts.bankofamerica.com",
    "subject": "Your statement is available",
    "snippet": "Your statement is available Account: ADV SAFEBALANCE BANKING 8618 "
    "View statement Ask Erica, View my statement",
}
AMEX_NO_PAYMENT = {
    "from": "AmericanExpress@welcome.americanexpress.com",
    "subject": "Your June 2026 Statement is Ready",
    "snippet": "Account Ending: 41007 Your June 2026 statement is ready Payment is "
    "not required. View your statement To include balance information",
}
AMEX_SAVINGS = {
    "from": "AmericanExpress@welcome.americanexpress.com",
    "subject": "New bank statement available",
    "snippet": "Account ending: 3333 New bank statement available the statement for "
    "your High Yield Savings Account ending in 3333",
}
BOA_CARD_1 = {
    "from": "onlinebanking@ealerts.bankofamerica.com",
    "subject": "Your credit card statement is available",
    "snippet": "Your credit card statement is available Account Everyday Rewards Visa "
    "Signature - 1111 Statement Date May 15, 2026 Total Minimum Payment Due $25.00 "
    "Statement Balance $1234.56 VIEW STATEMENT",
}
BOA_CARD_2 = {
    "from": "onlinebanking@ealerts.bankofamerica.com",
    "subject": "Your credit card statement is available",
    "snippet": "Your credit card statement is available Account Cash Back Rewards "
    "Visa Signature - 2222 Statement Date May 15, 2026 Total Minimum Payment Due $35.00 "
    "Statement Balance $500.00 VIEW STATEMENT",
}


# --- Classification --------------------------------------------------------

def test_deposit_statement_is_not_a_card_bill() -> None:
    row = R.classify_email(BOA_SAFEBALANCE)
    assert row["category"] == "statement"
    assert row["is_bill"] is False


def test_no_payment_required_notice_is_not_a_bill() -> None:
    row = R.classify_email(AMEX_NO_PAYMENT)
    assert row["category"] == "statement"
    assert row["is_bill"] is False


def test_savings_statement_is_not_a_bill() -> None:
    assert R.classify_email(AMEX_SAVINGS)["category"] == "statement"


def test_real_credit_card_statement_is_a_bill() -> None:
    row = R.classify_email(BOA_CARD_1)
    assert row["category"] == "bill_cc"
    assert row["is_bill"] is True


# --- Extraction ------------------------------------------------------------

def test_extracts_balance_minimum_and_account_tail() -> None:
    assert R.extract_amount(BOA_CARD_1["snippet"]) == "$1234.56"
    assert R.extract_minimum(BOA_CARD_1["snippet"]) == "$25.00"
    tail = R.extract_account_tail(BOA_CARD_1["subject"], BOA_CARD_1["snippet"], "")
    assert tail == "1111"


# --- Two cards, one issuer -------------------------------------------------

def _as_bill(snip: dict) -> dict:
    row = R.classify_email(snip)
    row["amount"] = R.extract_amount(snip["snippet"])
    row["minimum"] = R.extract_minimum(snip["snippet"])
    row["due_date"] = ""
    row["payee"] = R._bill_payee(row)
    row["account_tail"] = R.extract_account_tail(snip["subject"], snip["snippet"], "")
    return row


def test_two_cards_from_one_issuer_stay_separate_with_amounts() -> None:
    import datetime as dt

    tasks = R.bill_tasks_from_emails([_as_bill(BOA_CARD_1), _as_bill(BOA_CARD_2)], dt.date.today())
    assert len(tasks) == 2
    joined = "\n".join(tasks)
    assert "1111" in joined and "2222" in joined
    assert "$1234.56" in joined and "$500.00" in joined
    assert "min $25.00" in joined and "min $35.00" in joined


def test_render_line_shows_balance_and_min() -> None:
    line = R._render_mail_line(_as_bill(BOA_CARD_1))
    assert "$1234.56" in line and "min $25.00" in line
    assert "…1111" in line
