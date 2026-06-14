# Staged Git push guide

Use these commits when publishing to GitHub slowly. Each message maps to [CHANGELOG.md](../CHANGELOG.md).

**Never commit:** `.env`, `config.toml`, `credentials.json`, `token.json`, `logs/`.

## Suggested sequence

```bash
# 1 — repo hygiene
git add .gitignore LICENSE config.example.toml
git commit -m "chore: gitignore secrets, add MIT license and config example"

# 2 — module split
git add config.py vault.py rules.py coach.py note_io.py reminders.py lookback.py
git commit -m "refactor: split orchestrator into config, rules, coach, note_io, reminders"

# 3 — Google integration (if not already committed)
git add google_auth.py stress_test.py pyproject.toml uv.lock
git commit -m "feat: Google Calendar and Gmail with bill detection and stress test"

# 4 — documentation
git add README.md CHANGELOG.md docs/ INTEGRATIONS_PLAN.md .env.example
git commit -m "docs: README, CHANGELOG, push guide; mark integrations plan implemented"

# 5 — version tag
git commit -m "chore: release v0.5.0"  # only if pyproject version bump is staged
git tag v0.5.0
```

## Verify before each push

```bash
uv run python -m py_compile *.py
uv run lookback.py --dry-run
uv run python stress_test.py   # after Google auth
```

## GitHub repo setup

1. Create empty repo on GitHub (no README if you already have one locally).
2. `git remote add origin git@github.com:YOURUSER/daily-lookback.git`
3. Push branches incrementally: `git push -u origin main`

Replace commit hashes in CHANGELOG compare URLs when the repo URL is known.
