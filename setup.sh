#!/bin/bash
# One-command setup for macOS: installs deps, Playwright browser,
# and registers a LaunchAgent so the bot runs 24/7 (auto-start on login).
set -e
cd "$(dirname "$0")"

echo "== 1/4 Python venv =="
python3 -m venv .venv
./.venv/bin/pip install -q playwright pytz playwright-stealth requests

echo "== 2/4 Playwright Chromium =="
./.venv/bin/python -m playwright install chromium

echo "== 3/4 Directories =="
mkdir -p logs debug tock_session

echo "== 4/4 LaunchAgent (24/7 auto-start) =="
PLIST="$HOME/Library/LaunchAgents/com.fuhuihua.booker.plist"
sed "s|/Users/REPLACE|$HOME|g" com.fuhuihua.booker.plist.template > "$PLIST"
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

echo ""
echo "Done! The bot is now running 24/7 in the background."
echo "Next: export your Tock login -> python3 auth.py  (opens a browser, log in with Google)"
echo "Logs: tail -f logs/booker-*.log"
echo "Stop:  launchctl unload $PLIST"
