"""google_auth.py — one-time OAuth, then silent refresh. Read-only scopes.

First run opens a browser once for consent and writes token.json. Every run
after that refreshes silently, so the midnight job needs no human.

Setup (one-time):
  1. Google Cloud console → new project → enable Gmail API + Calendar API.
  2. OAuth client ID → Desktop app → download JSON as `credentials.json` here.
  3. Run:  uv run python google_auth.py     (opens browser, click Allow)
"""
from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).parent
CREDS = HERE / "credentials.json"
TOKEN = HERE / "token.json"

# Read-only — this code can never send, delete, or modify your mail/calendar.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
]


def _creds():
    # Imported lazily so the rest of the project runs even if the Google
    # libraries aren't installed yet (reminders degrade gracefully).
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = (
        Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
        if TOKEN.exists()
        else None
    )
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())  # silent — the nightly path
    else:
        if not CREDS.exists():
            raise SystemExit(
                f"Missing {CREDS.name}. Download an OAuth 'Desktop app' client from "
                "Google Cloud console and save it there. See INTEGRATIONS_PLAN.md §3."
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(CREDS), SCOPES)
        creds = flow.run_local_server(port=0)  # one-time browser consent
    TOKEN.write_text(creds.to_json())
    return creds


def _client(api: str, version: str):
    from googleapiclient.discovery import build

    return build(api, version, credentials=_creds(), cache_discovery=False)


def gmail_client():
    return _client("gmail", "v1")


def calendar_client():
    return _client("calendar", "v3")


def is_configured() -> bool:
    """True if at least the OAuth client secret is present (auth can proceed)."""
    return CREDS.exists()


if __name__ == "__main__":
    # Run this once to perform the initial consent and create token.json.
    gmail_client()
    calendar_client()
    print("Authenticated. token.json written — the midnight job is now hands-free.")
