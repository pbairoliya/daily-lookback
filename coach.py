"""coach.py — Ollama JSON coach for daily planning."""
from __future__ import annotations

import json
import subprocess
import time
import urllib.error
import urllib.request

from config import (
    DEFAULT_MODEL,
    OLLAMA_MAX_RETRIES,
    OLLAMA_NUM_CTX,
    OLLAMA_READY_TIMEOUT,
    OLLAMA_TAGS_URL,
    OLLAMA_URL,
)

SYSTEM_PROMPT = """You are a warm, concise daily-planning coach.
You read the past few days of journal entries, tasks, and focus areas, then help the user set up today.

Output STRICT JSON ONLY — a single object with EVERY field below populated. No markdown fences, no prose, no commentary.

Required schema (every key must appear, every array non-empty):
  - "focus":           array of 2-3 strings
  - "task_groups":     array of {"group": string, "items": [string]}
  - "blog_ideas":      array of 2-3 strings
  - "wins_prompts":    array of 2-3 strings
  - "journal_prompts": array of 2-3 strings
  - "tomorrow":        array of 1-3 strings
  - "lookback":        string

Rules:
- Ground every item in the *themes and momentum* of the recent notes — not in their literal text.
- NEVER echo a prior day's focus line, and NEVER re-suggest anything in FORBIDDEN.
- "focus" must be NEW direction for today; include one stretch item.
- Every REQUIRED task MUST appear in exactly one task_groups bucket.
- If REQUIRED starts with "Prep / pack", put it in the FIRST bucket as urgent.
- Put EVERY REQUIRED item starting with "Pay " together in ONE bucket named exactly "Bills & Payments". Never mix a payment into a work/learning/home/body bucket.
- NEVER invent shave, laundry, cleaning, groceries, or appointments unless REQUIRED.
- The JOURNAL, WINS, and LEARNINGS sections are REFLECTIONS of what ALREADY happened. NEVER turn anything written there into a task — if the user wrote "went for a run" or "called mom", that is DONE, not a to-do. Journal text may only shape journal_prompts, wins_prompts, and the lookback tone.
- Beyond REQUIRED add at most 0-3 new tasks, and only forward-looking ones for TODAY (next steps on current momentum). NEVER restate something the notes say is already done or merely mentioned in passing. Plain text only in strings.
- wins_prompts and journal_prompts must be questions.
- When EXTERNAL is present, journal_prompts MUST tie to a trip, appointment, or email there.
- When YESTERDAY'S JOURNAL is present, 1-2 journal_prompts MUST be gentle follow-ups that reference a specific phrase or feeling the user actually wrote there ("You mentioned feeling stuck on X — did anything shift?"). Quote or paraphrase their words; never invent feelings they didn't express.
- When SLIPPED is present, weave exactly ONE slipped task into "lookback" — curious and kind, never shaming (e.g. "the dentist call has waited 5 days; is something making it heavy?").
- EXTERNAL is CONTEXT ONLY. NEVER turn an email/calendar/reminder line into a task_groups item. Do NOT copy email senders, subjects, "[Bill due]"/"[Decision]"/"[FYI]" labels, or quoted subjects into tasks. The only money tasks allowed are the "Pay …" items already in REQUIRED.
"""


def _ollama_up() -> bool:
    try:
        with urllib.request.urlopen(OLLAMA_TAGS_URL, timeout=5) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False


# The `ollama serve` process THIS run started (None = server was already up,
# i.e. the user runs it themselves — we must not touch that one).
_managed_ollama: subprocess.Popen | None = None


def wait_for_ollama(timeout: int = OLLAMA_READY_TIMEOUT) -> None:
    """Make Ollama available for this run, starting a managed instance if needed.

    Ollama should NOT sit resident eating RAM all day: if the server is
    already up (the user started it to test things), use it and leave it
    alone afterward. If it's down, start it as a tracked child process —
    never detached, so shutdown_ollama() can stop it when the run finishes.
    """
    global _managed_ollama
    if _ollama_up():
        return
    print("Ollama not running — starting a managed instance for this run…")
    try:
        _managed_ollama = subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        print("`ollama` binary not on PATH; will keep polling in case it's booting.")

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _ollama_up():
            print("Ollama is up.")
            time.sleep(2)
            return
        time.sleep(3)
    shutdown_ollama()
    raise SystemExit(
        f"Ollama did not become ready within {timeout}s at {OLLAMA_URL}. "
        "Run `ollama serve` and try again."
    )


def shutdown_ollama() -> None:
    """Stop the Ollama instance this run started; free the RAM.

    A user-started server (_managed_ollama is None) is left untouched.
    """
    global _managed_ollama
    if _managed_ollama is None:
        return
    print("Stopping managed Ollama (freeing RAM)…")
    _managed_ollama.terminate()
    try:
        _managed_ollama.wait(timeout=15)
    except subprocess.TimeoutExpired:
        _managed_ollama.kill()
        _managed_ollama.wait(timeout=5)
    _managed_ollama = None


def as_list(plan: dict, key: str) -> list[str]:
    v = plan.get(key, [])
    if not isinstance(v, list):
        return []
    return [str(x).strip() for x in v if str(x).strip()]


def ask_coach(
    context: str,
    forbidden: list[str],
    required: list[str],
    model: str = DEFAULT_MODEL,
    external_context: str = "",
    yesterday_journal: str = "",
    slipped: list[tuple[str, int]] | None = None,
) -> dict:
    forbidden_block = (
        "FORBIDDEN (already shipped — must NOT appear in focus, task_groups, or anywhere else):\n"
        + "\n".join(f"- {x}" for x in forbidden)
        if forbidden
        else "FORBIDDEN: (none)"
    )
    required_block = (
        "REQUIRED tasks (every one MUST appear inside exactly one task_groups bucket):\n"
        + "\n".join(f"- {x}" for x in required)
        if required
        else "REQUIRED tasks: (none — feel free to populate task_groups from your own suggestions)"
    )
    external_block = f"\n\n{external_context}\n" if external_context.strip() else ""
    journal_block = (
        f"\n\nYESTERDAY'S JOURNAL (the user's own words — follow up on these):\n"
        f"{yesterday_journal.strip()}\n"
        if yesterday_journal.strip()
        else ""
    )
    slipped_block = (
        "\n\nSLIPPED (carried over unchecked this many consecutive days):\n"
        + "\n".join(f"- {t} ({n} days)" for t, n in slipped)
        + "\n"
        if slipped
        else ""
    )
    user_prompt = (
        f"Recent notes (newest first):\n\n{context}\n\n"
        f"{forbidden_block}\n\n"
        f"{required_block}"
        f"{external_block}"
        f"{journal_block}"
        f"{slipped_block}\n\n"
        "Now produce the JSON object. Remember: every REQUIRED task must land in a bucket, "
        "and nothing from FORBIDDEN may appear."
    )
    payload = {
        "model": model,
        "system": SYSTEM_PROMPT,
        "prompt": user_prompt,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.5, "num_ctx": OLLAMA_NUM_CTX},
    }

    def _parse(body: dict) -> dict | None:
        raw = body.get("response", "").strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.lower().startswith("json"):
                raw = raw[4:].lstrip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
        # Salvage a JSON object embedded in prose or with trailing junk.
        start, end = raw.find("{"), raw.rfind("}")
        if 0 <= start < end:
            try:
                return json.loads(raw[start : end + 1])
            except json.JSONDecodeError:
                pass
        return None

    def _plan_ok(plan: dict | None) -> bool:
        return bool(
            plan
            and isinstance(plan.get("task_groups"), list)
            and plan["task_groups"]
            and as_list(plan, "focus")
        )

    last_err: Exception | None = None
    last_plan: dict | None = None
    for attempt in range(1, OLLAMA_MAX_RETRIES + 1):
        req = urllib.request.Request(
            OLLAMA_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                body = json.loads(resp.read())
        except urllib.error.URLError as e:
            last_err = e
            print(f"Ollama call failed (attempt {attempt}/{OLLAMA_MAX_RETRIES}): {e}")
            wait_for_ollama()
            continue
        used = body.get("prompt_eval_count")
        if isinstance(used, int) and used >= OLLAMA_NUM_CTX - 64:
            print(
                f"WARNING: prompt filled the context window ({used}/{OLLAMA_NUM_CTX} "
                "tokens) — the system prompt was likely truncated. Raise "
                "[ollama] num_ctx in config.toml or trim the inputs."
            )
        plan = _parse(body)
        if _plan_ok(plan):
            return plan
        last_plan = plan
        print(f"Model returned an incomplete plan (attempt {attempt}/{OLLAMA_MAX_RETRIES}) — retrying…")

    if last_plan is not None:
        return last_plan
    raise SystemExit(
        f"Could not get a valid plan from Ollama at {OLLAMA_URL}: {last_err}\n"
        "Is `ollama serve` running and the model pulled?"
    )
