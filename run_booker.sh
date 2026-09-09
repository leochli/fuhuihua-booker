#!/bin/bash
# Supervisor for the Fuhuihua 24/7 bot.
# Restarts booker.py on crash with exponential backoff. Exits cleanly
# (no restart) when a booking succeeded (booking_confirmed.txt exists).
set -u
cd "$(dirname "$0")"

PY="./.venv/bin/python"
LOGDIR="logs"
mkdir -p "$LOGDIR" debug tock_session

backoff=10
while true; do
  if [ -f "booking_confirmed.txt" ]; then
    echo "$(date): booking confirmed — supervisor exiting."
    exit 0
  fi
  ts=$(date +%Y%m%d-%H%M%S)
  echo "$(date): starting booker.py (backoff was ${backoff}s)"
  # shellcheck disable=SC2086
  $PY booker.py >> "$LOGDIR/booker-$ts.log" 2>&1
  code=$?
  echo "$(date): booker.py exited with code $code"
  if [ "$code" -eq 0 ]; then
    # Clean exit (e.g. --once finished or booking done): don't hammer restarts
    sleep 30
    backoff=10
  else
    echo "$(date): restarting in ${backoff}s..."
    sleep "$backoff"
    backoff=$(( backoff * 2 ))
    if [ "$backoff" -gt 600 ]; then backoff=600; fi
  fi
done
