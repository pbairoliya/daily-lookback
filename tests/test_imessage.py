"""iMessage parsing against a fixture chat.db — no live Messages, no Ollama."""
import datetime as dt
import sqlite3
from pathlib import Path

import pytest

from imessage import _to_datetime, decode_attributed_body, fetch_messages, prefilter

_APPLE_EPOCH = dt.datetime(2001, 1, 1, tzinfo=dt.timezone.utc)


def _apple_ns(when: dt.datetime) -> int:
    return int((when - _APPLE_EPOCH).total_seconds() * 1_000_000_000)


def _typedstream_blob(text: str) -> bytes:
    """Minimal blob in the layout decode_attributed_body scans for."""
    payload = text.encode("utf-8")
    if len(payload) < 0x81:
        length = bytes([len(payload)])
    else:
        length = b"\x81" + len(payload).to_bytes(2, "little")
    return b"\x04\x0bstreamtyped\x81NSString\x01\x95\x84\x01+" + length + payload


@pytest.fixture
def chat_db(tmp_path: Path) -> Path:
    db = tmp_path / "chat.db"
    con = sqlite3.connect(db)
    con.executescript(
        """
        CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT);
        CREATE TABLE chat (ROWID INTEGER PRIMARY KEY, chat_identifier TEXT,
                           display_name TEXT);
        CREATE TABLE message (ROWID INTEGER PRIMARY KEY, date INTEGER,
                              is_from_me INTEGER, text TEXT,
                              attributedBody BLOB, handle_id INTEGER);
        CREATE TABLE chat_message_join (chat_id INTEGER, message_id INTEGER);
        """
    )
    now = dt.datetime.now(dt.timezone.utc)
    con.execute("INSERT INTO handle VALUES (1, '+15551234567')")
    con.execute("INSERT INTO chat VALUES (1, '+15551234567', 'Mom')")
    rows = [
        # plain-text ask from Mom, recent
        (1, _apple_ns(now - dt.timedelta(hours=5)), 0,
         "Can you send me the photos from the weekend?", None, 1),
        # NULL text, body only in attributedBody (modern macOS)
        (2, _apple_ns(now - dt.timedelta(hours=4)), 1, None,
         _typedstream_blob("I'll send them tonight, don't let me forget"), 1),
        # chatty noise — should be prefiltered out
        (3, _apple_ns(now - dt.timedelta(hours=3)), 0, "lol nice", None, 1),
        # too old — outside lookback window
        (4, _apple_ns(now - dt.timedelta(days=30)), 0,
         "Can you pay me back?", None, 1),
    ]
    con.executemany("INSERT INTO message VALUES (?,?,?,?,?,?)", rows)
    con.executemany(
        "INSERT INTO chat_message_join VALUES (1, ?)", [(1,), (2,), (3,), (4,)]
    )
    con.commit()
    con.close()
    return db


def test_decode_attributed_body() -> None:
    assert decode_attributed_body(_typedstream_blob("hello there")) == "hello there"
    long_text = "x" * 300  # exercises the 0x81 two-byte length path
    assert decode_attributed_body(_typedstream_blob(long_text)) == long_text
    assert decode_attributed_body(None) == ""
    assert decode_attributed_body(b"\x00garbage\xff") == ""


def test_fetch_messages(chat_db: Path) -> None:
    msgs = fetch_messages(days=3, allowlist=[], denylist=[], db_path=chat_db)
    assert [m["text"] for m in msgs] == [
        "Can you send me the photos from the weekend?",
        "I'll send them tonight, don't let me forget",
        "lol nice",
    ]
    assert msgs[0]["chat"] == "Mom"
    assert msgs[0]["is_from_me"] is False
    assert msgs[1]["is_from_me"] is True
    # Compare to the local date of the same "5 hours ago" anchor the fixture
    # used — robust when the test runs just after local midnight.
    expected = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=5)).astimezone().date()
    assert msgs[0]["when"].date() == expected


def test_fetch_respects_denylist(chat_db: Path) -> None:
    assert fetch_messages(days=3, allowlist=[], denylist=["mom"], db_path=chat_db) == []


def test_prefilter_keeps_signals_drops_noise(chat_db: Path) -> None:
    msgs = fetch_messages(days=3, allowlist=[], denylist=[], db_path=chat_db)
    kept = [m["text"] for m in prefilter(msgs)]
    assert "Can you send me the photos from the weekend?" in kept
    assert "I'll send them tonight, don't let me forget" in kept
    assert "lol nice" not in kept


def test_to_datetime_handles_seconds_and_nanoseconds() -> None:
    when = dt.datetime(2026, 6, 9, 12, 0, tzinfo=dt.timezone.utc)
    secs = int((when - _APPLE_EPOCH).total_seconds())
    assert _to_datetime(secs) == when
    assert _to_datetime(secs * 1_000_000_000) == when
