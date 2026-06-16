#!/usr/bin/env bash
# install_imessage_runtime.sh — build a STABLE, self-contained Python runtime for
# the nightly launchd job so Full Disk Access only has to be granted ONCE.
#
# Why: macOS Full Disk Access is keyed to the exact binary that opens chat.db.
# `uv run` launches a versioned managed interpreter
# (…/cpython-3.12.13-…/bin/python3.12) whose path changes on every uv Python
# upgrade — so the grant would keep breaking. uv's interpreters are relocatable
# (python-build-standalone), so we copy one to a fixed path we own, install the
# app's deps into it, and point launchd there. That binary never changes.
#
# Idempotent: safe to re-run (e.g. after changing dependencies in pyproject.toml).
set -euo pipefail

PROJ="$(cd "$(dirname "$0")/.." && pwd)"
RUNTIME="$HOME/.local/share/daily-lookback/runtime"
PYBIN="$RUNTIME/bin/python3"

echo "▶ Project:  $PROJ"
echo "▶ Runtime:  $RUNTIME"

# 1. Locate the uv-managed interpreter, resolving the .venv symlink down to the
#    real relocatable standalone install root (…/cpython-…-none).
SRC="$(cd "$PROJ" && uv python find)"
SRC_REAL="$(python3 -c "import os,sys;print(os.path.realpath(sys.argv[1]))" "$SRC")"
SRC_HOME="$(cd "$(dirname "$SRC_REAL")/.." && pwd)"   # standalone install root
echo "▶ Source:   $SRC_HOME"
# The real interpreter binary (python3 → python3.12 internally) must be a
# regular file, confirming this is the standalone install, not a thin venv.
if [ ! -f "$SRC_HOME/bin/python3.12" ] || [ -L "$SRC_HOME/bin/python3.12" ]; then
  echo "✗ Expected a self-contained standalone python at $SRC_HOME" >&2
  exit 1
fi

# 2. Copy it to the stable path (fresh each run so it tracks the source build).
#    Drop uv's "externally managed" marker — this copy is ours to install into.
rm -rf "$RUNTIME"
mkdir -p "$(dirname "$RUNTIME")"
cp -R "$SRC_HOME" "$RUNTIME"
rm -f "$RUNTIME"/lib/python3.12/EXTERNALLY-MANAGED

# 3. Install ONLY the locked runtime deps (not the project itself), straight
#    from uv.lock so there's no drift and no source build. Use the runtime's
#    own pip so uv never sees it as a managed interpreter.
echo "▶ Installing locked dependencies into the stable runtime…"
"$PYBIN" -m ensurepip --upgrade >/dev/null 2>&1 || true
( cd "$PROJ" && uv export --no-dev --no-emit-project --no-hashes 2>/dev/null ) \
  | "$PYBIN" -m pip install --no-input -r /dev/stdin >/dev/null

# 4. Smoke-test: the interpreter runs and the deps import.
"$PYBIN" - <<'PY'
import googleapiclient, google_auth_oauthlib, google_auth_httplib2  # noqa: F401
print("  ✓ runtime imports OK")
PY

echo
echo "✅ Stable runtime ready:"
echo "   $PYBIN"
echo
echo "NEXT — grant Full Disk Access to this ONE binary (only once, ever):"
echo "   System Settings → Privacy & Security → Full Disk Access → ＋"
echo "   In the picker press ⌘⇧G and paste:"
echo "   $PYBIN"
echo
echo "Then verify:  $PYBIN lookback.py --check-imessage"
