# Changelog

All notable changes to **daily-lookback** are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.6.0] - 2026-06-09

### Added

- `taskkeys.py`: canonical task identity (`task_key`/`bill_key`) — amounts,
  due dates, punctuation, and rewording no longer create duplicate tasks.
- `upsert_tasks`: a bill with a new amount/due date rewrites the existing
  line in place instead of appending a near-duplicate.
- iMessage integration (`imessage.py`, opt-in): commitments → tasks, texted
  plans → 💬 Messages reminders, anonymized themes → coach context. Local
  Ollama extraction only; requires Full Disk Access (docs/IMESSAGE.md).
- `--catch-up` + `runstate.py`: missed days (Mac off/asleep) are backfilled
  on the next fire; launchd plist (00:05, 09:00, RunAtLoad) now in repo with
  `scripts/install_launchd.sh` and a Makefile.
- Heartbeat ping (healthchecks.io style) — get a morning email if the
  nightly run never happened (docs/RELIABILITY.md).
- Therapist-mode coach: journal prompts follow up on yesterday's actual
  entry; accountability nudges for tasks slipping 3+ days; Sunday
  `🗓 Weekly Reflection` section (`weekly.py`, `--weekly` to force).
- Managed Ollama lifecycle: the run starts `ollama serve` if it's down and
  stops it afterward, so Ollama no longer sits in RAM all day. A
  user-started server is left untouched.
- Test suite (`tests/`, `uv run --group dev pytest`).

### Fixed

- Duplicate tasks from re-worded carry-overs, fresh bill statements, and
  coach re-suggestions (exact-text dedup replaced with key-based dedup at
  every merge layer).
- Coach silently returning incomplete plans: the full prompt overflowed
  `num_ctx 8192`, truncating the system prompt. Default is now 16384
  (`[ollama] num_ctx`), the note digest is capped per section, and an
  explicit warning fires on context overflow.

## [0.5.0] - 2026-05-31

### Added

- Google Calendar (±7 days) and Gmail (14 days) integration via read-only OAuth.
- `🔔 Reminders` section: past week, today, bills, inbox, trips, upcoming events.
- Ollama email triage; deterministic bill tasks from payment mail.
- Trip prep (day before) and packing heads-up (2 days out); journal seeds from calendar.
- `stress_test.py` for Calendar/Gmail smoke tests.
- Cadence tasks: quick clean, trash, credit card bills, apartment rent.
- Laundry quiet period (4 days after a logged fold).

### Changed

- Refactored into modules: `config`, `vault`, `rules`, `coach`, `note_io`, `reminders`, `lookback`.
- Configuration via `config.toml` + environment variables (`config.example.toml`).
- Local LLM coach uses Ollama JSON mode (not cloud Claude).

### Fixed

- Ollama readiness polling for midnight launchd runs.
- Cadence fold patterns no longer collide with generic "laundry" completions.

## [0.4.0] - 2026-05-28

### Added

- Deterministic life rules: shave (Mon/Wed/Fri/Sun + 2-day gap), laundry cycles, cadence chores.
- Structured JSON plan: focus, task groups, journal prompts, looking back.
- Carry-over of incomplete non-recurring tasks; forbidden list from prior completions.

## [0.3.0] - 2026-05-26

### Added

- Idempotent section injection (Looking back, empty-section fill only).
- Task buckets with **Bold** group headers.
- `wait_for_ollama()` with retries.

## [0.2.0] - 2026-05-24

### Added

- `vault.py`: read daily notes, parse tasks, extract sections.
- Basic context digest from recent notes.

## [0.1.0] - 2026-05-22

### Added

- Initial project scaffold and tutorial milestones.

[0.6.0]: https://github.com/yourusername/daily-lookback/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/yourusername/daily-lookback/releases/tag/v0.5.0
