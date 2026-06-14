# How a run works (end-to-end)

Each `uv run lookback.py` pass does the following in order.

## 1. Read vault (`vault.py`)

- Last N daily notes (default 5), excluding today’s file.
- Build a **context digest** (`build_context`): journal, focus, learnings, wins, **prior saved Reminders blocks**, completed vs open tasks.

**Not in the vault digest:** live Google Calendar/Gmail for today. Those are fetched in step 3 and appended as `EXTERNAL` to the coach prompt plus `## 🔔 Reminders` on today's note.

**"Tomorrow notes"** in the digest = your hand-written `## 🔜 Tomorrow` section from past days, not calendar events.

## 2. Deterministic rules (`rules.py`)

Python decides chores — the LLM does not guess.

| Input | Output |
|-------|--------|
| Past completed tasks | **Cadence** due (groceries, sheets, bills, …) |
| Shave history + weekday | **Shave** on REQUIRED or FORBIDDEN |
| Last fold date | **Laundry quiet** (no laundry tasks for 4 days) |
| Carry-over list | Open non-recurring tasks from prior notes |

## 3. Google (`reminders.py`)

| Step | Function | Feeds |
|------|----------|--------|
| Calendar ±7d | `load_calendar()` | Reminders section + EXTERNAL coach context + trip pack tasks |
| Gmail 14d | `load_gmail()` after Ollama up | Reminders section + bill REQUIRED tasks + EXTERNAL |

Without `credentials.json` / `token.json`, calendar and mail are empty; the note still generates.

## 4. Coach (`coach.py`)

Ollama returns JSON: `focus`, `task_groups`, `journal_prompts`, `wins_prompts`, `tomorrow`, `lookback`, …

- **REQUIRED** list (recurring + carry + cadence + shave + bills + trips) must appear in task buckets.
- **EXTERNAL** block adds calendar/inbox lines so journal questions reference real events.

## 5. Write note (`note_io.py` + `lookback.py`)

| Section | Behavior |
|---------|----------|
| **Reminders** | `inject_section` — **always replaced** (calendar, bills, inbox, trips) |
| **Looking back** | `inject_section` — **always replaced** (+ suppression notes) |
| **Focus / Blog / Wins** | `fill_if_empty` — only if section blank |
| **Journal / Tomorrow** | `refresh_prompts` — replace if empty or still only `?` bullets; keep your prose |
| **Tasks** | If pristine: full bucket layout from coach. If already edited: **append** missing REQUIRED + carry |

## What “smart tasks” means here

Tasks in **✅ Tasks** come from:

1. Template recurring habits (Shower, Work, …)
2. Carry-over from older notes
3. Cadence engine (Python)
4. Shave / laundry rules (Python)
5. Trip prep / pack (Calendar)
6. Pay rent / credit card (Gmail)
7. Coach buckets (Ollama), which must include all REQUIRED items

## Quick verification

```bash
uv run lookback.py --dry-run
```

Read the `--- Run summary ---` block and the `## 🔔 Reminders` section in the output.
