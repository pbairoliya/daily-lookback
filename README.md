# daily-lookback

A local-first CLI that prepares your **Obsidian daily note** each morning: it reads recent notes, applies deterministic life rules (shave days, laundry quiet, cadence chores), pulls **Google Calendar and Gmail**, asks **Ollama** for a structured plan, and writes Focus, Tasks, Journal prompts, Reminders, and Looking back — idempotently.

> **Privacy:** Notes and LLM calls stay on your machine. Google scopes are read-only. Email subjects land in your iCloud-synced vault only if you enable Reminders.

## Architecture

```
Obsidian Daily/*.md
       │
       ▼
  vault.py (parse tasks, sections)
       │
       ├── rules.py ──► REQUIRED / FORBIDDEN (shave, laundry, cadence)
       │
       ├── reminders.py ──► Calendar ±7d, Gmail 14d, bills
       │
       ▼
  coach.py (Ollama JSON plan)
       │
       ▼
  note_io.py ──► inject into today's .md
```

## Quick start

```bash
cd daily-lookback
uv sync
ollama pull gemma3
ollama serve   # if not already running

cp config.example.toml config.toml   # edit paths for your vault
uv run lookback.py --dry-run
uv run lookback.py
```

### Google Calendar + Gmail (optional)

1. [Google Cloud](https://console.cloud.google.com/) → enable Gmail API + Calendar API → OAuth **Desktop** client → save `credentials.json` in this folder.
2. One-time: `uv run python google_auth.py`
3. Test: `uv run python stress_test.py`

See [INTEGRATIONS_PLAN.md](INTEGRATIONS_PLAN.md) (implemented design doc).

## Configuration

| Source | Purpose |
|--------|---------|
| [config.example.toml](config.example.toml) | Copy to `config.toml` (gitignored) |
| `DAILY_VAULT_DIR` | Override Obsidian Daily folder |
| `DAILY_TEMPLATE_PATH` | Daily Note template path |
| `OLLAMA_MODEL` | Default `gemma3` |

## Life rules (why not the LLM?)

Small local models guess wrong on day-of-week and "don't repeat yesterday." Python encodes:

- **Shave:** Mon/Wed/Fri/Sun only, 2-day minimum gap.
- **Laundry:** 4-day quiet period after logging a fold.
- **Cadence:** groceries, sheets, deep clean, bills, trash, etc. from completed-task history.
- **Trips:** pack task the day before; packing list 2 days out.

The model only **buckets** tasks into themed groups — it does not invent suppressed chores.

## What gets written each run

| Section | Updated when |
|---------|----------------|
| 🔔 Reminders | Every run (Calendar + Gmail) |
| 🪞 Looking back | Every run |
| 📓 Journal / 🔜 Tomorrow | When empty or still only prompt questions |
| 🎯 Focus / Blog / Wins | Only when section is empty |
| ✅ Tasks | Full buckets first time; later runs append missing smart/required tasks |

See [docs/FLOW.md](docs/FLOW.md) for the full pipeline.

## CLI

```bash
uv run lookback.py [--dry-run] [--date YYYY-MM-DD] [--days N] [--model NAME]
                   [--catch-up] [--weekly] [--check-imessage]
uv run python stress_test.py [--triage]
uv run --group dev pytest        # unit tests (or: make test)
```

## Automation & reliability

```bash
make install-agent   # launchd: 00:05 + 09:00 + on-boot, with --catch-up
make run-now         # fire immediately
make logs            # tail run logs
```

Missed nights (Mac off/asleep) are backfilled by `--catch-up` on the next
fire; an optional [healthchecks.io](https://healthchecks.io) heartbeat emails
you if the run never happened. The run starts Ollama itself when needed and
stops it afterward, so it doesn't sit in RAM all day. See
[docs/RELIABILITY.md](docs/RELIABILITY.md).

## iMessage (optional, local-only)

Commitments from texts become tasks, texted plans land in 🔔 Reminders, and
anonymized emotional themes shape the journal prompts — all extracted by
local Ollama, nothing leaves the machine. Enable `[imessage]` in
`config.toml` after granting Full Disk Access; see
[docs/IMESSAGE.md](docs/IMESSAGE.md).

## Project layout

| File | Role |
|------|------|
| [lookback.py](lookback.py) | CLI orchestrator |
| [config.py](config.py) | Paths and Ollama settings |
| [vault.py](vault.py) | Read/parse Obsidian notes |
| [rules.py](rules.py) | Deterministic chore logic |
| [coach.py](coach.py) | Ollama JSON coach |
| [note_io.py](note_io.py) | Section inject / task render |
| [reminders.py](reminders.py) | Google fetch + Reminders markdown |
| [taskkeys.py](taskkeys.py) | Canonical task identity (dedup keys) |
| [imessage.py](imessage.py) | Local Messages → tasks/plans/themes |
| [weekly.py](weekly.py) | Sunday weekly reflection |
| [runstate.py](runstate.py) | Catch-up state + heartbeat ping |
| [google_auth.py](google_auth.py) | OAuth token refresh |
| [stress_test.py](stress_test.py) | Integration smoke test |
| [tests/](tests/) | Unit tests (dedup, upsert, catch-up, iMessage) |

## Changelog

See [CHANGELOG.md](CHANGELOG.md).

## License

MIT — see [LICENSE](LICENSE).

## Blog

Outline for a write-up: [docs/BLOG_OUTLINE.md](docs/BLOG_OUTLINE.md).
