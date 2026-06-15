"""Recent-receipts feed surfaced in the daily note."""
import datetime as dt
import json

import pytest

import receipts_feed
from receipts_feed import recent_receipts, render_receipt_lines

TODAY = dt.date(2026, 6, 15)


@pytest.fixture
def index(tmp_path, monkeypatch):
    path = tmp_path / ".receipts.jsonl"
    monkeypatch.setattr(receipts_feed, "RECEIPTS_INDEX", path)
    return path


def _write(path, records):
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")


def test_window_and_status_filter(index):
    _write(index, [
        {"store": "Safeway", "date": "2026-06-14", "total": 52.38, "type": "groceries",
         "items": [1, 2, 3], "status": "complete"},
        {"store": "Old", "date": "2026-06-01", "total": 9.0, "type": "other", "status": "complete"},
        {"store": "Pending", "date": "2026-06-15", "total": 5.0, "type": "other",
         "status": "needs-review"},
        {"store": "Future", "date": "2026-06-20", "total": 5.0, "type": "other",
         "status": "complete"},
    ])
    out = recent_receipts(TODAY, days=2)
    assert [r["store"] for r in out] == ["Safeway"]  # in-window + complete only


def test_newest_first(index):
    _write(index, [
        {"store": "A", "date": "2026-06-14", "time": "09:00", "total": 1, "type": "other",
         "status": "complete"},
        {"store": "B", "date": "2026-06-15", "time": "08:00", "total": 2, "type": "other",
         "status": "complete"},
    ])
    assert [r["store"] for r in recent_receipts(TODAY, days=2)] == ["B", "A"]


def test_render_includes_total_when_multiple(index):
    recs = [
        {"store": "Safeway", "date": "2026-06-14", "total": 52.38, "type": "groceries",
         "items": list(range(12)), "status": "complete", "_date": dt.date(2026, 6, 14)},
        {"store": "Trader Joe's", "date": "2026-06-14", "total": 69.92, "type": "groceries",
         "items": list(range(17)), "status": "complete", "_date": dt.date(2026, 6, 14)},
    ]
    lines = render_receipt_lines(recs)
    assert any("Safeway" in l and "$52.38" in l and "12 items" in l for l in lines)
    assert any("Total: $122.30 across 2 receipts" in l for l in lines)


def test_missing_index_is_safe(tmp_path, monkeypatch):
    monkeypatch.setattr(receipts_feed, "RECEIPTS_INDEX", tmp_path / "nope.jsonl")
    assert recent_receipts(TODAY) == []
    assert render_receipt_lines([]) == []


def test_tolerates_torn_line(index):
    index.write_text(
        json.dumps({"store": "Good", "date": "2026-06-14", "total": 5, "type": "other",
                    "status": "complete"})
        + "\n{ this is a half-written line"
    )
    assert [r["store"] for r in recent_receipts(TODAY, days=2)] == ["Good"]
