# iMessage integration

Pulls signals from the local Messages database into the daily note —
entirely on-device (extraction runs on local Ollama; nothing leaves the
Mac):

- **Tasks** — commitments you made or were asked for ("Send Mom the
  photos") flow into REQUIRED tasks (deduped like everything else).
- **Plans** — texted meetups/dates render under **💬 Messages** in the
  🔔 Reminders section.
- **Themes** — 2-4 anonymized emotional observations ("a friend is
  stressed about a move") feed the coach so journal prompts reflect what's
  actually going on. Phrased by relationship, never by name.

## Enabling

```toml
[imessage]
enabled = true
lookback_days = 3
allowlist = []   # only these contacts/chats (substring match); empty = everyone
denylist = []    # always skip these
```

## Full Disk Access (the fiddly part)

`~/Library/Messages/chat.db` is TCC-protected. macOS attributes access to
the **responsible binary** — for a LaunchAgent that's the executable in
`ProgramArguments[0]` (`/bin/zsh` with the bundled plist).

1. System Settings → Privacy & Security → Full Disk Access → add the
   binary that runs lookback:
   - for the bundled plist: the `uv` binary (press Cmd+Shift+G in the file
     picker and paste the output of `command -v uv`, e.g.
     `/opt/homebrew/bin/uv`)
   - for manual runs: your terminal app (Terminal/iTerm)
2. Verify interactively: `uv run lookback.py --check-imessage` → `PASS`.
3. Verify headless (this is the one that matters):
   `make run-now`, then check `logs/lookback.err.log` for an iMessage
   access complaint, or temporarily look for the `iMessage:` line in
   `logs/lookback.out.log`.

If headless access fails while Terminal works, the launchd binary isn't
the one you granted. Re-check step 1 against `ProgramArguments[0]` in
`~/Library/LaunchAgents/com.pbairol.daily-lookback.plist`.

## Safety properties

- The live `chat.db` is never opened — a snapshot copy (plus `-wal`/`-shm`
  sidecars) is read from a temp dir, read-only.
- Disabled by default; every failure (no FDA, missing db, Ollama down,
  bad JSON) degrades to "no message signals", never a crashed run.
- `attributedBody` decoding (modern macOS stores the text there, not in
  `message.text`) is a best-effort typedstream scan; undecodable messages
  are skipped.
