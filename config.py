"""config.py — paths and runtime settings (config.toml + env overrides)."""
from __future__ import annotations

import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG_FILE = HERE / "config.toml"


def _expand(path: str) -> Path:
    return Path(os.path.expanduser(path)).resolve()


def _load_toml() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    try:
        import tomllib
    except ImportError:
        return {}
    with CONFIG_FILE.open("rb") as f:
        return tomllib.load(f)


def _env_list(name: str, fallback: list) -> list[str]:
    raw = os.environ.get(name)
    if raw is None:
        return [str(x) for x in fallback]
    return [s.strip() for s in raw.split(",") if s.strip()]


_cfg = _load_toml()
_daily = _cfg.get("daily", {})
_ollama = _cfg.get("ollama", {})
_calendar = _cfg.get("calendar", {})
_gmail = _cfg.get("gmail", {})
_imessage = _cfg.get("imessage", {})
_heartbeat = _cfg.get("heartbeat", {})
_catchup = _cfg.get("catchup", {})
_coach = _cfg.get("coach", {})
_receipts = _cfg.get("receipts", {})

_DEFAULT_DAILY = (
    "~/Library/Mobile Documents/iCloud~md~obsidian/Documents/pbrain/Daily"
)
_DEFAULT_TEMPLATE = (
    "~/Library/Mobile Documents/iCloud~md~obsidian/Documents/pbrain/"
    "Templates/Daily Note.md"
)

DAILY_DIR: Path = _expand(
    os.environ.get("DAILY_VAULT_DIR", _daily.get("vault_daily_dir", _DEFAULT_DAILY))
)
TEMPLATE_PATH: Path = _expand(
    os.environ.get(
        "DAILY_TEMPLATE_PATH",
        _daily.get("template_path", _DEFAULT_TEMPLATE),
    )
)

DEFAULT_MODEL: str = os.environ.get(
    "OLLAMA_MODEL", _ollama.get("model", "gemma3")
)
OLLAMA_URL: str = os.environ.get(
    "OLLAMA_URL", _ollama.get("url", "http://localhost:11434/api/generate")
)
OLLAMA_TAGS_URL: str = os.environ.get(
    "OLLAMA_TAGS_URL",
    _ollama.get("tags_url", "http://localhost:11434/api/tags"),
)
OLLAMA_READY_TIMEOUT: int = int(
    os.environ.get("OLLAMA_READY_TIMEOUT", _ollama.get("ready_timeout", 120))
)
OLLAMA_MAX_RETRIES: int = int(
    os.environ.get("OLLAMA_MAX_RETRIES", _ollama.get("max_retries", 3))
)
# Context window for generate calls. The full coach prompt (5-day digest +
# calendar/email context + rules) runs ~9-10k tokens; 8192 silently truncates
# the system prompt and the model returns schema-less JSON.
OLLAMA_NUM_CTX: int = int(
    os.environ.get("OLLAMA_NUM_CTX", _ollama.get("num_ctx", 16384))
)

CALENDAR_LOOKBACK_DAYS: int = int(
    os.environ.get("CALENDAR_LOOKBACK_DAYS", _calendar.get("lookback_days", 14))
)
CALENDAR_LOOKAHEAD_DAYS: int = int(
    os.environ.get("CALENDAR_LOOKAHEAD_DAYS", _calendar.get("lookahead_days", 7))
)
GMAIL_LOOKBACK_DAYS: int = int(
    os.environ.get("GMAIL_LOOKBACK_DAYS", _gmail.get("lookback_days", 14))
)

IMESSAGE_ENABLED: bool = os.environ.get(
    "IMESSAGE_ENABLED", str(_imessage.get("enabled", False))
).lower() in ("1", "true", "yes")
IMESSAGE_LOOKBACK_DAYS: int = int(
    os.environ.get("IMESSAGE_LOOKBACK_DAYS", _imessage.get("lookback_days", 3))
)
IMESSAGE_ALLOWLIST: list[str] = _env_list(
    "IMESSAGE_ALLOWLIST", _imessage.get("allowlist", [])
)
IMESSAGE_DENYLIST: list[str] = _env_list(
    "IMESSAGE_DENYLIST", _imessage.get("denylist", [])
)
# {digit-only handle fragment: display label}. Labels replace raw numbers in the
# LLM payload and the note (privacy + the model knows who's who).
IMESSAGE_CONTACTS: dict[str, str] = {
    str(k): str(v) for k, v in dict(_imessage.get("contacts", {})).items()
}
# One line about who these people are and what you'd hate to miss. Steers the
# extraction prompt; kept in config so no personal detail lives in the source.
IMESSAGE_FOCUS: str = os.environ.get("IMESSAGE_FOCUS", str(_imessage.get("focus", "")))

# Dead-man's-switch ping URL (e.g. https://hc-ping.com/<uuid>); empty = off.
HEARTBEAT_URL: str = os.environ.get("HEARTBEAT_URL", _heartbeat.get("url", ""))

MAX_BACKFILL_DAYS: int = int(
    os.environ.get("MAX_BACKFILL_DAYS", _catchup.get("max_backfill_days", 7))
)
# "stub": missed past days get a template-only note; "full": full pipeline.
BACKFILL_MODE: str = os.environ.get(
    "BACKFILL_MODE", _catchup.get("backfill_mode", "stub")
)

# Tasks carried over this many consecutive days get an accountability nudge.
NUDGE_AFTER_DAYS: int = int(
    os.environ.get("NUDGE_AFTER_DAYS", _coach.get("nudge_after_days", 3))
)
# A bill is only surfaced (as a task or reminder) once it's within this many days
# of its due date — so a statement that arrives 3 weeks early stays quiet until
# it's actually worth paying. Overdue and undated bills are always shown.
BILL_LEAD_DAYS: int = int(
    os.environ.get("BILL_LEAD_DAYS", _coach.get("bill_lead_days", 3))
)
WEEKLY_ENABLED: bool = os.environ.get(
    "WEEKLY_ENABLED", str(_coach.get("weekly_enabled", True))
).lower() in ("1", "true", "yes")

# Recent-spend feed: surface receipts the grocery-receipts app logged in the
# last couple of days. Index is that app's shared JSONL in the vault.
_DEFAULT_RECEIPTS_INDEX = (
    "~/Library/Mobile Documents/iCloud~md~obsidian/Documents/pbrain/"
    "Receipts/.receipts.jsonl"
)
RECEIPTS_ENABLED: bool = os.environ.get(
    "RECEIPTS_ENABLED", str(_receipts.get("enabled", True))
).lower() in ("1", "true", "yes")
RECEIPTS_INDEX: Path = _expand(
    os.environ.get("RECEIPTS_INDEX", _receipts.get("index", _DEFAULT_RECEIPTS_INDEX))
)
RECEIPTS_LOOKBACK_DAYS: int = int(
    os.environ.get("RECEIPTS_LOOKBACK_DAYS", _receipts.get("lookback_days", 2))
)
