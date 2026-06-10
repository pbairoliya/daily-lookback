"""taskkeys.py — canonical task identity for dedup across all layers.

A "task key" is what makes two task strings the *same task* even when their
surface text drifts: amounts change between statements, due dates roll
forward, the coach rewords a carry-over. Every layer that decides "is this
task already here?" (carry-over, REQUIRED assembly, note merge, bucket
rendering) must compare keys, never raw text.

This module is import-free on purpose (stdlib only) so it can be used from
note_io, rules, and lookback without creating import cycles.
"""
from __future__ import annotations

import re

# "Pay …" prefixes that mark a payment/bill task. Kept here (not note_io) so
# bill_key and note rendering agree on what counts as a bill.
PAYMENT_PREFIXES = ("pay rent", "pay credit card", "pay bill", "pay apartment")

_AMOUNT_RE = re.compile(r"\$\s?\d[\d,]*(?:\.\d{1,2})?")
_TRAILING_PAREN_RE = re.compile(r"\s*\([^)]*\)\s*$")

_MONTH = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?"
    r"|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?"
    r"|dec(?:ember)?)"
)
_DOW = r"(?:mon|tues?|wed(?:nes)?|thu(?:rs?)?|fri|sat(?:ur)?|sun)(?:day)?"
_DATE_RES = [
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
    re.compile(r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b"),
    re.compile(
        rf"\b(?:due|by|on|before)\s+(?:{_DOW}\s*,?\s*)?{_MONTH}\.?\s*"
        r"\d{1,2}(?:st|nd|rd|th)?(?:,?\s*\d{4})?\b"
    ),
    re.compile(rf"\b{_MONTH}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s*\d{{4}})?\b"),
    re.compile(rf"\b(?:due|by)\s+{_DOW}\b"),
    re.compile(r"\bdue\s+\d{1,2}(?:st|nd|rd|th)?\b"),
]


def is_payment_task(s: str) -> bool:
    return s.lower().lstrip().startswith(PAYMENT_PREFIXES)


def task_key(s: str) -> str:
    """Canonical identity key: lowercase; strip $amounts, date-shaped tokens,
    and a trailing parenthetical detail blob; drop punctuation; collapse
    whitespace. Bare numbers survive ("Read ch. 3" != "Read ch. 4").

    'Pay rent — Bozzuto ($2,450, due 06/01)' -> 'pay rent bozzuto'
    """
    t = s.lower().strip()
    t = _TRAILING_PAREN_RE.sub("", t)
    t = _AMOUNT_RE.sub(" ", t)
    for rx in _DATE_RES:
        t = rx.sub(" ", t)
    t = re.sub(r"[^a-z0-9 ]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def bill_key(s: str) -> str | None:
    """Payee-identity key for payment tasks, or None for everything else.

    Coarser than task_key: drops the ': subject…' tail that
    bill_tasks_from_emails appends when no amount is known, so the same
    payee's bill matches across statements regardless of subject wording.
    """
    if not is_payment_task(s):
        return None
    head = s.split(":", 1)[0]
    return task_key(head) or task_key(s)


def dedup_by_key(items: list[str]) -> list[str]:
    """Order-preserving dedup by task_key; first occurrence's text wins."""
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        t = (it or "").strip()
        if not t:
            continue
        k = task_key(t) or t.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(t)
    return out
