# Reliability: never miss a day

The nightly run survives the Mac mini being asleep or powered off through
three layers, plus an external alert if all of them fail.

## 1. launchd agent with catch-up

`make install-agent` installs `launchd/com.pbairol.daily-lookback.plist`,
which runs `uv run lookback.py --catch-up`:

- **00:05** — the normal nightly run.
- **09:00** — retry in case the Mac slept through midnight.
- **RunAtLoad** — fires on every boot/login, so a powered-off night is
  backfilled at startup.

`--catch-up` reads `~/.local/state/daily-lookback/last_run` and processes
every missed date since the last successful run (capped by
`[catchup] max_backfill_days`, default 7). Redundant fires are free no-ops:
if today already ran, it exits immediately. Missed *past* days are written
as template stub notes by default (`backfill_mode = "stub"`); set
`backfill_mode = "full"` to run the whole pipeline for each missed day.

launchd notes: macOS coalesces a `StartCalendarInterval` missed during
*sleep* into one fire on wake, but a *powered-off* interval is gone —
that's what `RunAtLoad` covers.

**Ollama lifecycle:** the run starts `ollama serve` itself when the server
is down and stops it again when the run finishes, so Ollama doesn't sit in
RAM all day. If the server is already up (you started it to test), the run
uses it and leaves it running.

## 2. Nightly wake

Schedule the mini to wake (or power on) just before midnight:

```sh
sudo pmset repeat wakeorpoweron MTWRFSU 00:04:00
```

Verify with `pmset -g sched`.

## 3. Heartbeat alert (healthchecks.io)

If the mini stays dead, nothing local can tell you — an external
dead-man's switch can. Create a free check at <https://healthchecks.io>
(schedule: daily; grace: until ~10:00), then add it to `config.toml`:

```toml
[heartbeat]
url = "https://hc-ping.com/<your-uuid>"
```

Every successful run pings the URL; a pipeline failure pings `<url>/fail`
for an immediate alert. If no ping arrives by the grace deadline (machine
off, Ollama dead, vault unreachable), healthchecks.io emails you that
morning.

## Testing the setup

```sh
make install-agent          # install + bootstrap the agent
make run-now                # fire it immediately via launchctl kickstart
make logs                   # tail stdout/stderr logs
echo 2026-06-06 > ~/.local/state/daily-lookback/last_run
make catch-up               # watch it backfill the gap
```
