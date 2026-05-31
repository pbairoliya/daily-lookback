# Pratik's TODO — connect Google (Calendar + Gmail)

Everything in code is done (deps installed, `google_auth.py` + `reminders.py` wired,
read-only scopes). These are the **manual steps only you can do**. ~15 min, one time.

## Decide first
- [ ] **Which Google account?** Use the one with the calendar + important mail you want
      surfaced. Your finance/important mail is under **pratik0520@gmail.com** — use that
      unless your real calendar lives on another account. (One account per `token.json`.)

## In Google Cloud Console  →  https://console.cloud.google.com/
- [ ] **Create a project** — name it `daily-lookback`. (top bar → project dropdown → New)
- [ ] **Enable the two APIs** — APIs & Services → *Enable APIs and Services* → enable:
  - [ ] **Gmail API**
  - [ ] **Google Calendar API**
- [ ] **OAuth consent screen** — *External* → fill app name + your email →
      add **yourself as a Test user**.
- [ ] **⚠️ Publish to Production** — on the consent screen, click *Publish App* →
      Production. If you leave it in "Testing", the refresh token **expires every 7 days**
      and the midnight job silently loses Gmail/Calendar. (It's just you on read-only
      scopes — no Google verification review needed.)
- [ ] **Create the credential** — Credentials → *Create Credentials* → *OAuth client ID*
      → application type **Desktop app** → Create → **Download JSON**.
- [ ] **Save it** as `credentials.json` in:
      `/Users/pbairol/ai-engineering/daily-lookback/credentials.json`
      (already gitignored — never commit it.)

## On your Mac (Terminal)
- [ ] **One-time consent** — opens a browser, click *Allow* on both scopes:
      ```
      cd ~/ai-engineering/daily-lookback
      uv run python google_auth.py
      ```
      Success = `token.json` appears. After this the midnight job is hands-free.
- [ ] **Smoke test** the live fetch:
      ```
      uv run python stress_test.py
      ```
- [ ] **See it in a note** (won't overwrite hand-written sections):
      ```
      uv run lookback.py --dry-run
      ```
      Confirm the **🔔 Reminders** section now lists real calendar events + flagged mail.

## Optional / later
- [ ] If your vault paths ever differ, `cp config.example.toml config.toml` and edit.
- [ ] Tune the Gmail filter (VIP senders, keywords) in `reminders.py` once you see what
      it surfaces — e.g. add `from:@yourbank.com` or `subject:(interview OR deadline)`.

---
**Done when:** `token.json` exists **and** `--dry-run` shows your real events/mail under
🔔 Reminders. Then nightly runs pull them automatically — no further action.
