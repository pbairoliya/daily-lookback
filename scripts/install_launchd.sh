#!/bin/zsh
# Install (or reinstall) the daily-lookback launchd agent.
set -euo pipefail

LABEL="com.pbairol.daily-lookback"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PLIST_SRC="$PROJECT_DIR/launchd/$LABEL.plist"
PLIST_DST="$HOME/Library/LaunchAgents/$LABEL.plist"
UV_BIN="$(command -v uv)"

if [[ -z "$UV_BIN" ]]; then
    echo "error: uv not found on PATH" >&2
    exit 1
fi

mkdir -p "$PROJECT_DIR/logs" "$HOME/Library/LaunchAgents"
sed -e "s|__PROJECT_DIR__|$PROJECT_DIR|g" -e "s|__UV__|$UV_BIN|g" \
    -e "s|__HOME__|$HOME|g" \
    "$PLIST_SRC" > "$PLIST_DST"

launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UID" "$PLIST_DST"

echo "Installed $LABEL → $PLIST_DST"
echo
echo "Next steps:"
echo "  1. Wake the Mac nightly for the midnight run:"
echo "       sudo pmset repeat wakeorpoweron MTWRFSU 00:04:00"
echo "  2. (iMessage only) Grant Full Disk Access to $UV_BIN in"
echo "     System Settings → Privacy & Security → Full Disk Access,"
echo "     then verify headless: make run-now && tail logs/lookback.err.log"
echo "  3. Test now: launchctl kickstart -k gui/$UID/$LABEL"
