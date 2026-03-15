# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Fuhuihua Booker is a Playwright-based bot that auto-books restaurant reservations on Tock (exploretock.com) when new slots drop. It detects the release time from the page, waits, polls rapidly, and navigates Tock's multi-step prepaid checkout flow.

## Commands

```bash
# Setup
conda env create -f environment.yml
conda activate fuhuihua-booker
python -m playwright install chromium   # or firefox
python auth.py                          # one-time cookie import from laptop browser

# Run
python book.py                # wait for drop, then book
python book.py --now          # book immediately (skip wait)
python book.py --dry-run --now  # find slot but don't book

# Recon (availability monitoring)
python recon.py --interval 60 --duration 48   # poll every 60s for 48h, logs to recon_log.jsonl
```

## Architecture

Five Python modules, no tests, no build system:

- **`book.py`** — Main bot. `BookingBot` class handles the full flow: load page → detect release time → wait → poll for slots → click experience → navigate checkout (party size → time → cart → payment → confirm). Uses file lock (`booking.lock`) and marker file (`booking_confirmed.txt`) to prevent duplicate bookings.
- **`recon.py`** — Standalone availability monitor. Polls Tock at intervals, logs changes to `recon_log.jsonl`. Uses Chromium only (no Firefox option).
- **`auth.py`** — One-time cookie exporter. User logs into Tock via Google OAuth on their laptop browser, runs a JS snippet to copy cookies, pastes them here. Saves Playwright storage state to `tock_session/state.json`.
- **`config.py`** — All configuration: target URL, party size, preferred dates, drop time, polling intervals, notification method, browser settings (headless, Firefox vs Chromium), proxy.
- **`notify.py`** — Notification dispatch: console (default), Twilio SMS, Telegram, Pushover. Each backend falls back to console on failure.

## Key Design Decisions

- **Firefox preferred over Chromium** (`USE_FIREFOX = True` in config) — Cloudflare detects headless Chromium more aggressively. `playwright-stealth` is only applied for Chromium.
- **Session-based auth** — Google OAuth can't be automated headlessly, so cookies are manually exported once and reused via Playwright's `storage_state`.
- **Three-layer booking guard** — file lock (single instance), marker file (cross-run), in-memory flag (within session). Delete `booking_confirmed.txt` to allow re-booking.
- **Jittered polling** — Random delays added to poll intervals and page interactions to reduce bot detection.
- **Proxy support** — `PROXY_SERVER` in config for devservers behind a forward proxy; empty string means direct connection.
