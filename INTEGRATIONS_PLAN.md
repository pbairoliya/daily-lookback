# Reminders Integration Plan — Gmail + Calendar → Daily Note

> **Status: Implemented** (see [CHANGELOG.md](CHANGELOG.md) v0.5.0). This document remains as the original design appendix.

**Goal:** Add a live **🔔 Reminders** section to the top of each daily note that pulls
*today's calendar events* and *important / actionable emails* — generated automatically
by the same midnight `lookback.py` run, fully local-first.

This builds on the existing pipeline (`vault.py` → `lookback.py` → Obsidian note) and the
resilience fix that now waits for Ollama before generating.

---

## 0. The end-state (what you're building toward)

The daily note gains one new section, injected right under the H1 title, **above Today's Focus**:

```markdown
# Saturday, May 30, 2026

## 🔔 Reminders
> Auto-pulled at 00:01. Calendar + important inbox. Edit freely — regenerated daily.

**📅 Today**
- 09:30–10:00  Standup (Google Meet)
- 14:00–15:00  Dentist — 123 Main St
- ⏳ All-day: Rent due

**📬 Needs a reply / action**
- [ ] **Spencer** — "Re: failed cycle accounts" (2h ago) — asks for the updated list
- [ ] **Chase** — statement ready, autopay confirms in 3 days
- [ ] **Recruiter @ Acme** — wants to schedule a call this week

**🗓 Tomorrow (heads-up)**
- 11:00  Flight to SFO — leave by 08:30

## 🎯 Today's Focus
...
```

Everything in this section is **regenerated each day** (idempotent, like `🪞 Looking back`),
so you never hand-edit it — you act on it, then it refreshes tomorrow.

---

## 1. Architecture decision — Google API (local OAuth), not MCP

There are two ways to reach Gmail/Calendar:

| Option | Good for | Why not here |
|---|---|---|
| **Claude MCP connectors** (the Gmail/Calendar tools in this chat) | Interactive, ad-hoc asks | Can't run headless at 00:01 from launchd. Needs an interactive Claude session + auth. |
| **Google API + local OAuth** ✅ | A scheduled, unattended script | One-time consent, then a stored **refresh token** runs forever with no human in the loop. |

Since `lookback.py` runs **unattended at midnight via launchd**, we use the **Google API**
directly (`google-api-python-client`). One-time browser consent → `token.json` on disk →
silent refresh every night. This is the same model Ollama gives you: local, no recurring
cloud cost, no key to babysit.

> Use the MCP connectors in *this chat* for exploration ("what important mail came in
> today?") — but the automation owns its own OAuth token.

---

## 2. Module layout

Two new files, mirroring the clean split you already have (`vault.py` = pure I/O, no AI):

```
daily-lookback/
  vault.py            # (exists) Obsidian read/parse
  lookback.py         # (exists) orchestrator — gains a Reminders step
  google_auth.py      # NEW: one-time OAuth + token refresh, returns API clients
  reminders.py        # NEW: fetch calendar + gmail, return structured reminders
  credentials.json    # NEW: from Google Cloud (gitignored)
  token.json          # NEW: created on first auth (gitignored)
```

Keep `reminders.py` "pure-ish" (fetch + shape data), like `vault.py`. Keep rendering in
`lookback.py`, like the existing section injectors.

---

## 3. Phase 0 — Google Cloud setup (one-time, ~10 min)

1. Go to <https://console.cloud.google.com/> → create a project, e.g. **`daily-lookback`**.
   - Sign in as the account whose mail/calendar you want — likely **pratik0520@gmail.com**
     (your finance/primary account) or whichever holds the important mail.
2. **Enable APIs**: APIs & Services → Enable APIs → enable **Gmail API** and **Google Calendar API**.
3. **OAuth consent screen**: choose **External**, fill app name + your email. Add yourself
   under **Test users** (so you don't need Google verification). Publishing status can stay
   "Testing" — test tokens just need a refresh every 7 days *unless* you set the app to
   "In production" (recommended; one click, removes the 7-day expiry).
4. **Create credentials** → OAuth client ID → **Desktop app** → download JSON →
   save as `daily-lookback/credentials.json`.
5. **Scopes** (request read-only — least privilege):
   - `https://www.googleapis.com/auth/gmail.readonly`
   - `https://www.googleapis.com/auth/calendar.readonly`

> Add `credentials.json` and `token.json` to `.gitignore` immediately. They're secrets.

---

## 4. Phase 1 — `google_auth.py` (auth + token refresh)

```python
"""google_auth.py — one-time OAuth, then silent refresh. Read-only scopes."""
from __future__ import annotations
from pathlib import Path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

HERE = Path(__file__).parent
CREDS = HERE / "credentials.json"
TOKEN = HERE / "token.json"
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
]

def _creds() -> Credentials:
    creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES) if TOKEN.exists() else None
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())              # silent — the nightly path
    else:
        # first run only: opens a browser once, you click "Allow"
        flow = InstalledAppFlow.from_client_secrets_file(str(CREDS), SCOPES)
        creds = flow.run_local_server(port=0)
    TOKEN.write_text(creds.to_json())
    return creds

def gmail_client():
    return build("gmail", "v1", credentials=_creds(), cache_discovery=False)

def calendar_client():
    return build("calendar", "v3", credentials=_creds(), cache_discovery=False)
```

**First-time auth must be run by a human once** (it opens a browser):

```bash
uv run python -c "import google_auth; google_auth.gmail_client(); print('authed')"
```

After that, `token.json` exists and the midnight job refreshes silently — no browser.

---

## 5. Phase 2 — Calendar fetch (`reminders.py`)

```python
import datetime as dt
from google_auth import calendar_client

def todays_events(now: dt.datetime) -> list[dict]:
    svc = calendar_client()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + dt.timedelta(days=2)            # today + tomorrow heads-up
    resp = svc.events().list(
        calendarId="primary",
        timeMin=start.isoformat() + "Z",
        timeMax=end.isoformat() + "Z",
        singleEvents=True, orderBy="startTime",
    ).execute()
    out = []
    for e in resp.get("items", []):
        s = e["start"].get("dateTime", e["start"].get("date"))
        out.append({
            "summary": e.get("summary", "(no title)"),
            "start": s,
            "all_day": "date" in e["start"],
            "location": e.get("location", ""),
            "is_today": s.startswith(start.date().isoformat()),
        })
    return out
```

---

## 6. Phase 3 — Gmail "important / actionable" filtering

This is the heart of it. Two layers: a **cheap Gmail-side query** to shrink the candidate
set, then an **optional Ollama pass** to decide what's truly *actionable*.

### 6a. Gmail query (server-side filter — free, fast)

Gmail's own search operators do most of the work. Pull only recent, unread, signal-heavy mail:

```python
from google_auth import gmail_client

# "important" per Gmail's own ML markers, OR starred, OR direct-to-you & unread, last 2 days
QUERY = "newer_than:2d -category:promotions -category:social (is:important OR is:starred OR (is:unread to:me))"

def candidate_emails(max_n: int = 15) -> list[dict]:
    svc = gmail_client()
    ids = svc.users().messages().list(userId="me", q=QUERY, maxResults=max_n).execute().get("messages", [])
    out = []
    for m in ids:
        msg = svc.users().messages().get(
            userId="me", id=m["id"], format="metadata",
            metadataHeaders=["From", "Subject", "Date"]
        ).execute()
        h = {x["name"]: x["value"] for x in msg["payload"]["headers"]}
        out.append({
            "from": h.get("From", ""),
            "subject": h.get("Subject", "(no subject)"),
            "date": h.get("Date", ""),
            "snippet": msg.get("snippet", ""),
            "labels": msg.get("labelIds", []),
        })
    return out
```

Useful operators to tune the query later: `from:`, `label:`, `has:attachment`,
`subject:(invoice OR deadline OR interview)`, a VIP allowlist
`(from:spencer@... OR from:@chase.com OR from:@yourbank.com)`.

### 6b. Optional Ollama classification (turns "candidates" → "needs action")

Gmail's `is:important` is decent but noisy. Pass the candidates through your local model
to keep only mail that *actually needs a reply or a decision* and one-line why. Reuses the
exact `ask_coach`/Ollama JSON pattern already in `lookback.py`:

```python
TRIAGE_PROMPT = """You are an inbox triage assistant. From the emails below, return STRICT JSON:
{"actionable":[{"from":str,"subject":str,"why":str,"urgency":"high|med|low"}]}
Keep ONLY emails that need a reply, a decision, or have a deadline. Drop newsletters,
receipts, notifications, marketing. "why" = max 8 words on what's needed. No prose."""
```

(Call Ollama exactly like `ask_coach` does — `format:"json"`, `stream:false`, `gemma3`.)
If Ollama triage feels like overkill at first, **ship 6a alone** (raw Gmail-importance) and
add 6b later. The architecture supports both.

---

## 7. Phase 4 — Render + inject into the note

Add a heading constant and a renderer in `lookback.py`, reusing `inject_section()`
(already idempotent — it replaces the section every run, like `🪞 Looking back`):

```python
REMINDERS_HEADING = "🔔 Reminders"

def render_reminders(events: list[dict], mails: list[dict]) -> str:
    lines = ["> Auto-pulled at 00:01. Edit freely — regenerated daily.", ""]
    today = [e for e in events if e["is_today"]]
    tomo  = [e for e in events if not e["is_today"]]
    if today:
        lines.append("**📅 Today**")
        for e in today:
            when = "⏳ All-day" if e["all_day"] else _fmt_time(e["start"])
            loc = f" — {e['location']}" if e["location"] else ""
            lines.append(f"- {when}  {e['summary']}{loc}")
        lines.append("")
    if mails:
        lines.append("**📬 Needs a reply / action**")
        for m in mails:
            who = _short_from(m["from"])
            why = f" — {m['why']}" if m.get("why") else ""
            lines.append(f"- [ ] **{who}** — \"{m['subject']}\"{why}")
        lines.append("")
    if tomo:
        lines.append("**🗓 Tomorrow (heads-up)**")
        for e in tomo:
            when = "All-day" if e["all_day"] else _fmt_time(e["start"])
            lines.append(f"- {when}  {e['summary']}")
    return "\n".join(lines).strip() or "- (nothing pulled today)"
```

Then in `main()`, **after** `wait_for_ollama()` and the note is loaded/rendered:

```python
note = inject_section(note, REMINDERS_HEADING, render_reminders(events, mails))
```

`inject_section` already inserts right after the H1 — exactly where we want it.

### Template change (optional but cleaner)
Add a placeholder section to `Templates/Daily Note.md` so new notes have it even before the
script runs:

```markdown
## 🔔 Reminders
> Auto-pulled at 00:01 from Calendar + important inbox.
-
```

---

## 8. Phase 5 — Wire into `lookback.py` with failure isolation

**Critical rule: Google being down must NOT break note generation.** Wrap the fetch so a
network/auth hiccup degrades gracefully (the rest of the note still writes — same philosophy
as the Ollama retry fix):

```python
try:
    events = todays_events(dt.datetime.now())
    mails  = triage_emails(candidate_emails())   # 6a + optional 6b
except Exception as e:
    print(f"Reminders fetch failed ({e}); writing note without them.")
    events, mails = [], []
note = inject_section(note, REMINDERS_HEADING, render_reminders(events, mails))
```

### Dependencies (uv)
```bash
cd ~/ai-engineering/daily-lookback
uv add google-api-python-client google-auth-httplib2 google-auth-oauthlib
```

---

## 9. Security & privacy

- **Scopes are read-only** (`gmail.readonly`, `calendar.readonly`) — the script can never
  send, delete, or modify anything.
- `credentials.json` + `token.json` → **`.gitignore`** (they're account secrets). Add them
  before the first commit.
- Email **bodies never leave your machine** — Gmail → local Python → local Ollama → local
  Obsidian note. No cloud LLM, nothing uploaded.
- The note itself lands in your **iCloud-synced** Obsidian vault. If you don't want email
  subjects syncing to iCloud, consider redacting to sender-only, or keep Reminders in a
  separate non-synced note.
- Set the OAuth app to **"In production"** to avoid the 7-day test-token expiry.

---

## 10. Build order (milestones — match your project's M-style)

- [ ] **M1 — Cloud setup**: project, APIs enabled, `credentials.json` downloaded, gitignored.
- [ ] **M2 — Auth**: `google_auth.py`; run the one-time browser consent; `token.json` created.
- [ ] **M3 — Calendar**: `todays_events()` prints today's events in the terminal.
- [ ] **M4 — Gmail raw**: `candidate_emails()` prints the Gmail-importance candidate set.
- [ ] **M5 — Render**: `render_reminders()` + `inject_section` into a `--dry-run` note.
- [ ] **M6 — Wire + isolate**: into `main()` with the try/except guard; full run writes today.
- [ ] **M7 — Ollama triage** (stretch): add 6b to cut inbox noise to true action items.
- [ ] **M8 — Tune**: VIP allowlist, query operators, urgency sorting.

Each milestone is independently testable from the CLI before touching the midnight job —
same discipline as `vault.py`.

---

## 11. Stretch ideas (later)

- **Two-way tasks**: turn `📬 Needs a reply` items into real `- [ ]` tasks in the Tasks
  section so carry-over logic tracks them until you reply.
- **Deadline mining**: regex/LLM-extract dates from email bodies → feed the cadence engine.
- **Calendar gaps**: have the coach suggest deep-work blocks in free calendar windows.
- **Morning digest**: a second launchd job at 07:00 that re-pulls reminders (catches
  overnight mail the 00:01 run missed).
- **Bill/finance hook**: filter `from:@chase.com OR subject:(statement OR payment due)` →
  drop into the `💰 Money Note` section, tying into your finance workflow.

---

### Recap of the automation fix already shipped
`lookback.py` now calls `wait_for_ollama()` (auto-starts `ollama serve`, polls up to 120s)
before asking the model, and retries the generate call. The 00:01 launchd job is loaded and
will fire tonight; the previously-missing **2026-05-30** note was backfilled. The same
"degrade gracefully, never lose the note" principle carries into the reminders fetch above.
