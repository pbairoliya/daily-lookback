# Blog post outline: daily-lookback

Working title: **Your Obsidian daily note, but it actually knows your calendar**

## Hook

- Obsidian Templates can't reason about yesterday's tasks, your inbox, or shave day.
- This is a small Python job that runs at midnight and writes into today's note locally.

## Architecture (diagram)

- Obsidian vault (read/write daily notes)
- Python rules engine (deterministic chores)
- Ollama (local JSON coach for focus, buckets, journal prompts)
- Google Calendar + Gmail (read-only, optional)

## Key idea: Python decides, LLM phrases

- Why a small model must not choose shave/laundry/cadence days.
- REQUIRED vs FORBIDDEN lists fed into the prompt.
- Laundry quiet period example.

## Google integration

- OAuth desktop flow, token refresh, headless cron.
- Reminders section vs coach EXTERNAL context.
- Bill mail: dual Gmail query + never-drop triage.

## Idempotent note surgery

- `inject_section` for Looking back and Reminders.
- `fill_if_empty` so hand-edited sections stay untouched.

## Config for open source

- `config.example.toml` — no personal paths in git.

## Call to action

- Clone, copy config, `uv run lookback.py --dry-run`.
- Link to repo and stress_test.

## Screenshots to capture

- Reminders section with calendar + bills.
- Tasks with **bucket** headers.
- Looking back with "Why today's list differs".
