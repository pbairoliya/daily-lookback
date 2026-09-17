"""imessage.py — local-only Messages → tasks / plans / coach themes.

Reads a snapshot copy of ~/Library/Messages/chat.db (never the live file),
prefilters candidate messages deterministically, then makes ONE Ollama JSON
call to extract:
  - tasks:  commitments the user made or was asked for ("send mom the photos")
  - events: plans with a date ("dinner Friday with Alex")
  - themes: anonymized emotional context for the coach's journal prompts

Privacy: nothing leaves the machine — extraction runs on local Ollama, and
themes are phrased by relationship ("a friend"), never by name.

Requires Full Disk Access for whatever binary launchd runs (docs/IMESSAGE.md).
Disabled by default; every failure path degrades to empty results.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import shutil
import sqlite3
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from config import (
    IMESSAGE_ALLOWLIST,
    IMESSAGE_CONTACTS,
    IMESSAGE_DENYLIST,
    IMESSAGE_ENABLED,
    IMESSAGE_FOCUS,
    IMESSAGE_LOOKBACK_DAYS,
    OLLAMA_NUM_CTX,
)

CHAT_DB = Path("~/Library/Messages/chat.db").expanduser()

# Apple epoch: 2001-01-01 UTC; modern macOS stores nanoseconds.
_APPLE_EPOCH = dt.datetime(2001, 1, 1, tzinfo=dt.timezone.utc)

_MAX_CANDIDATES = 40
_MAX_MSG_CHARS = 200
# Hard ceiling on characters shipped to the local LLM — keeps the prompt small
# and fast even if the allowlisted threads are chatty. Newest messages win.
_MAX_PAYLOAD_CHARS = 6000

_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)

_SIGNAL_RES = [re.compile(p, re.IGNORECASE) for p in (
    r"\bcan you\b", r"\bcould you\b", r"\bwill you\b", r"\bdon'?t forget\b",
    r"\bremind\b", r"\bsend (?:me|him|her|them|it|the)\b", r"\blet me know\b",
    r"\bi(?:'| wi)ll\b", r"\bpay (?:me|you)\b", r"\bvenmo\b", r"\bzelle\b",
    r"\blet'?s\b", r"\bare we\b", r"\bdinner\b", r"\blunch\b", r"\bbrunch\b",
    r"\btonight\b", r"\btomorrow\b", r"\bthis week(?:end)?\b", r"\bnext week\b",
    r"\b(?:mon|tues|wednes|thurs|fri|satur|sun)day\b",
    r"\b\d{1,2}(?::\d{2})?\s?(?:am|pm)\b", r"\b\d{1,2}/\d{1,2}\b",
    r"https?://",  # shared links (articles, listings, docs) — surface them
)]

# The roster and the "what would I hate to miss" steer both come from config, so
# no real names live in this repo. See [imessage.contacts] and [imessage].focus.
_PROMPT_TEMPLATE = """You help the user keep up with the people closest to them.
{roster}Lines tagged "me" are the user.

Your job is to surface what the user might MISS.{focus} Be precise; do not invent
details that aren't in the messages.

Output STRICT JSON ONLY:
{{"tasks": [{{"text": string, "who": string}}],
 "events": [{{"text": string, "date": "YYYY-MM-DD or empty string"}}],
 "links": [{{"url": string, "why": string}}],
 "themes": [string]}}

Rules:
- tasks: concrete things the user should DO or follow up on (make the call, send
  the photos, refill the prescription). "who" = who it concerns. Max 5. Skip
  small talk.
- events: appointments / plans / visits with a date. Max 5.
- links: useful URLs someone shared (verbatim) with a short why. Max 3. Skip
  tracking/verification links and bare image URLs.
- themes: 2-4 short notes on how these people are doing, so the user stays aware.
- Empty arrays are fine. No commentary, JSON only."""


def build_extract_prompt(
    contacts: dict[str, str] | None = None, focus: str = ""
) -> str:
    """The extraction system prompt, personalised from config.

    `contacts` maps handle fragments to display labels; only the labels are used,
    so the roster tells the model who it is reading without this file ever
    knowing. `focus` is the user's own one-liner about what matters most.
    """
    labels = list(dict.fromkeys((contacts or {}).values()))
    roster = ""
    if labels:
        roster = "These messages are ONLY with:\n" + "".join(f"- {l}\n" for l in labels)
    focus = focus.strip()
    if focus and focus[-1] not in ".!?":
        focus += "."
    focus_line = f" Above all: {focus}" if focus else ""
    return _PROMPT_TEMPLATE.format(roster=roster, focus=focus_line)


EXTRACT_PROMPT = build_extract_prompt(IMESSAGE_CONTACTS, IMESSAGE_FOCUS)


def contact_label(row: dict) -> str:
    """Friendly label for a message's sender (e.g. 'Mom', 'Sam'), matched on
    the digits of the stored handle. Falls back to the chat name, never a number."""
    if row.get("is_from_me"):
        return "me"
    digits = re.sub(r"\D", "", str(row.get("sender", "")))
    for frag, label in IMESSAGE_CONTACTS.items():
        if frag and frag in digits:
            return label
    return row.get("chat") or "them"


def copy_chat_db(dest_dir: Path) -> Path:
    """Snapshot chat.db (+ WAL sidecars) so we never touch Messages' live lock."""
    dest = dest_dir / "chat.db"
    shutil.copy2(CHAT_DB, dest)
    for suffix in ("-wal", "-shm"):
        side = CHAT_DB.with_name(CHAT_DB.name + suffix)
        if side.exists():
            shutil.copy2(side, dest_dir / (dest.name + suffix))
    return dest


def decode_attributed_body(blob: bytes | None) -> str:
    """Pull the NSString payload out of a typedstream attributedBody blob.

    Modern macOS leaves message.text NULL and stores the body here. The
    typedstream format is undocumented; this marker-scan handles the common
    layout (NSString class marker, '+' data tag, then a length-prefixed
    UTF-8 run; 0x81 introduces a two-byte little-endian length).
    """
    if not blob:
        return ""
    try:
        idx = blob.find(b"NSString")
        if idx == -1:
            return ""
        idx = blob.find(b"+", idx)
        if idx == -1:
            return ""
        idx += 1
        length = blob[idx]
        idx += 1
        if length == 0x81:
            length = int.from_bytes(blob[idx : idx + 2], "little")
            idx += 2
        return blob[idx : idx + length].decode("utf-8", errors="ignore").strip()
    except Exception:  # noqa: BLE001 — never let a weird blob kill the run
        return ""


def _to_datetime(raw: int) -> dt.datetime:
    seconds = raw / 1_000_000_000 if raw > 1_000_000_000_000 else raw
    return (_APPLE_EPOCH + dt.timedelta(seconds=seconds)).astimezone()


def _contact_match(row: dict, names: list[str]) -> bool:
    hay = f"{row.get('sender', '')} {row.get('chat', '')}".lower()
    return any(n.lower() in hay for n in names)


def fetch_messages(
    days: int = IMESSAGE_LOOKBACK_DAYS,
    allowlist: list[str] | None = None,
    denylist: list[str] | None = None,
    db_path: Path | None = None,
) -> list[dict]:
    """Recent messages: {chat, sender, is_from_me, when, text}, oldest first."""
    allowlist = IMESSAGE_ALLOWLIST if allowlist is None else allowlist
    denylist = IMESSAGE_DENYLIST if denylist is None else denylist

    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    cutoff_ns = int((cutoff - _APPLE_EPOCH).total_seconds() * 1_000_000_000)

    with tempfile.TemporaryDirectory() as tmp:
        if db_path is None:
            db_path = copy_chat_db(Path(tmp))
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            rows = con.execute(
                """
                SELECT m.date, m.is_from_me, m.text, m.attributedBody,
                       COALESCE(h.id, '') AS handle,
                       COALESCE(c.display_name, c.chat_identifier, '') AS chat
                FROM message m
                LEFT JOIN handle h ON h.ROWID = m.handle_id
                LEFT JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
                LEFT JOIN chat c ON c.ROWID = cmj.chat_id
                WHERE m.date > ?
                ORDER BY m.date ASC
                """,
                (cutoff_ns,),
            ).fetchall()
        finally:
            con.close()

    out: list[dict] = []
    for date_raw, is_from_me, text, attr_body, handle, chat in rows:
        body = (text or "").strip() or decode_attributed_body(attr_body)
        if not body:
            continue
        row = {
            "chat": chat,
            "sender": "me" if is_from_me else (handle or "them"),
            "is_from_me": bool(is_from_me),
            "when": _to_datetime(date_raw),
            "text": body,
        }
        if denylist and _contact_match(row, denylist):
            continue
        if allowlist and not _contact_match(row, allowlist):
            continue
        out.append(row)
    return out


def prefilter(messages: list[dict]) -> list[dict]:
    """Deterministic candidate selection so the Ollama prompt stays small."""
    picked: list[dict] = []
    for m in messages:
        text = m["text"]
        if len(text) < 3:
            continue
        asks = not m["is_from_me"] and text.rstrip().endswith("?")
        if asks or any(rx.search(text) for rx in _SIGNAL_RES):
            picked.append(m)
    return picked[-_MAX_CANDIDATES:]


def extract_signals(
    candidates: list[dict],
    model: str,
    ollama_url: str = "http://localhost:11434/api/generate",
) -> dict:
    """One low-temperature JSON extraction call; tolerates partial output."""
    empty = {"tasks": [], "events": [], "links": [], "themes": []}
    if not candidates:
        return empty

    # Build newest-first under a hard character budget, then restore order — so
    # a chatty week still sends only a small, recent slice to the local model.
    lines: list[str] = []
    budget = _MAX_PAYLOAD_CHARS
    for m in reversed(candidates):
        when = m["when"].strftime("%a %b %d %H:%M")
        line = f"[{contact_label(m)}] ({when}): {m['text'][:_MAX_MSG_CHARS]}"
        if len(line) > budget:
            break
        budget -= len(line)
        lines.append(line)
    lines.reverse()
    payload = {
        "model": model,
        "system": EXTRACT_PROMPT,
        "prompt": "\n".join(lines),
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.1, "num_ctx": OLLAMA_NUM_CTX},
    }
    try:
        req = urllib.request.Request(
            ollama_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read())
        data = json.loads(body.get("response", "").strip())
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as e:
        print(f"iMessage extraction failed ({e}); skipping message signals.")
        return empty
    if not isinstance(data, dict):
        return empty
    for key in empty:
        if not isinstance(data.get(key), list):
            data[key] = []
    return data


def load_imessage(
    target: dt.date,
    model: str,
    ollama_url: str = "http://localhost:11434/api/generate",
) -> tuple[list[str], list[str], list[str]]:
    """(candidate_tasks, reminder_lines, themes) — all empty when disabled
    or when chat.db is unreadable (no Full Disk Access)."""
    _ = target
    if not IMESSAGE_ENABLED:
        return [], [], []
    if not CHAT_DB.exists():
        print(f"iMessage: {CHAT_DB} not found; skipping.")
        return [], [], []
    try:
        messages = fetch_messages()
    except (sqlite3.OperationalError, PermissionError, OSError) as e:
        print(
            f"iMessage: cannot read chat.db ({e}). Grant Full Disk Access to the "
            "binary that runs lookback (see docs/IMESSAGE.md); skipping."
        )
        return [], [], []

    candidates = prefilter(messages)
    data = extract_signals(candidates, model, ollama_url)

    tasks: list[str] = []
    for t in data["tasks"][:5]:
        if isinstance(t, dict) and str(t.get("text", "")).strip():
            text = str(t["text"]).strip()
            who = str(t.get("who", "")).strip()
            tasks.append(f"{text} ({who})" if who and who.lower() not in text.lower() else text)

    plans: list[str] = []
    for e in data["events"][:6]:
        if isinstance(e, dict) and str(e.get("text", "")).strip():
            date = str(e.get("date", "")).strip()
            plans.append(f"{date} — {e['text']}".strip(" —") if date else str(e["text"]).strip())

    # Links shared in chats — model-extracted, then a deterministic backstop so a
    # raw URL never slips through just because the model didn't tag it.
    seen_urls: set[str] = set()
    for ln in data.get("links", [])[:5]:
        if not isinstance(ln, dict):
            continue
        url = str(ln.get("url", "")).strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        why = str(ln.get("why", "")).strip()
        plans.append(f"🔗 {why}: {url}" if why else f"🔗 {url}")
    for m in candidates:
        if m["is_from_me"]:
            continue
        for url in _URL_RE.findall(m["text"]):
            url = url.rstrip(").,]")
            if url not in seen_urls and len(seen_urls) < 8:
                seen_urls.add(url)
                plans.append(f"🔗 from {contact_label(m)}: {url}")

    themes = [str(x).strip() for x in data["themes"][:4] if str(x).strip()]
    return tasks, plans, themes


def check_access() -> bool:
    """Self-test for --check-imessage: can we actually read chat.db here?"""
    if not CHAT_DB.exists():
        print(f"FAIL: {CHAT_DB} does not exist (is this the right user account?)")
        return False
    try:
        with tempfile.TemporaryDirectory() as tmp:
            db = copy_chat_db(Path(tmp))
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            try:
                (n,) = con.execute("SELECT COUNT(*) FROM message").fetchone()
            finally:
                con.close()
        print(f"PASS: chat.db readable ({n} messages).")
        return True
    except (sqlite3.OperationalError, PermissionError, OSError) as e:
        print(f"FAIL: cannot read chat.db ({e}). Grant Full Disk Access — see docs/IMESSAGE.md.")
        return False


if __name__ == "__main__":
    check_access()
