"""receipts_feed.py — surface recently-scanned receipts in the daily note.

Reads the grocery-receipts app's shared index (a JSONL in the vault, one record
per receipt: store / date / total / type / items / status) and renders a short
"recent spend" block. Read-only and best-effort: a missing or half-written index
never fails the daily run.
"""
from __future__ import annotations

import datetime as dt
import json

from config import RECEIPTS_INDEX, RECEIPTS_LOOKBACK_DAYS

# Per-category icon so the block scans at a glance.
_TYPE_ICON = {
    "groceries": "🛒",
    "car": "⛽",
    "health": "💊",
    "dining": "🍽️",
    "other": "🧾",
}


def _parse_date(s: str) -> dt.date | None:
    try:
        return dt.date.fromisoformat((s or "").strip()[:10])
    except ValueError:
        return None


def recent_receipts(today: dt.date, days: int = RECEIPTS_LOOKBACK_DAYS) -> list[dict]:
    """Completed receipts dated within the last `days` (inclusive), newest first."""
    try:
        lines = RECEIPTS_INDEX.read_text(encoding="utf-8").splitlines()
    except (FileNotFoundError, OSError):
        return []

    out: list[dict] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue  # tolerate a torn last line mid-write
        if rec.get("status") not in (None, "complete"):
            continue  # skip needs-review receipts — totals may be wrong
        rd = _parse_date(rec.get("date", ""))
        if rd is None or rd > today or (today - rd).days > days:
            continue
        rec["_date"] = rd
        out.append(rec)
    out.sort(key=lambda r: (r["_date"], r.get("time", "")), reverse=True)
    return out


def _fmt_total(total) -> str:
    try:
        return f"${float(total):.2f}"
    except (TypeError, ValueError):
        return "$?"


def render_receipt_lines(receipts: list[dict]) -> list[str]:
    """Markdown lines for the recent-spend block (empty list if nothing)."""
    if not receipts:
        return []
    lines: list[str] = []
    grand = 0.0
    have_total = False
    for r in receipts:
        icon = _TYPE_ICON.get(r.get("type", "other"), "🧾")
        store = (r.get("store") or "Unknown").strip()
        total = r.get("total")
        try:
            grand += float(total)
            have_total = True
        except (TypeError, ValueError):
            pass
        n_items = len(r.get("items") or [])
        item_tail = f" · {n_items} item{'s' if n_items != 1 else ''}" if n_items else ""
        when = r["_date"].strftime("%a %b %d")
        lines.append(f"- {icon} {when} — **{store}** {_fmt_total(total)}{item_tail}")
    if have_total and len(receipts) > 1:
        lines.append(f"- _Total: ${grand:.2f} across {len(receipts)} receipts_")
    return lines
