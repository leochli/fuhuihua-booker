# Fuhuihua Booking Bot

Auto-books a table at [Fui Hui Hua](https://www.exploretock.com/fui-hui-hua-san-francisco/) on Tock when reservations drop.

## How It Works

1. Loads the Tock page and detects the next reservation release time
2. Waits until the drop time, then polls rapidly for available slots
3. Clicks the first available experience/time slot
4. Navigates through Tock's checkout flow (party size → time → cart → payment)
5. Sends a notification on success

## Environment Setup

### Prerequisites

- **conda** (Miniconda or Anaconda)
- A browser (Chrome/Firefox) on your laptop for one-time cookie export

### 1. Create the conda environment

```bash
cd ~/fuhuihua-booker
conda env create -f environment.yml
conda activate fuhuihua-booker
```

### 2. Install Playwright browsers

```bash
# Use proxy if on a devserver that needs it
with-proxy python -m playwright install chromium
```

### 3. Export your Tock session (one-time)

Since Tock uses Google OAuth, you can't automate login from a headless server. Instead, export cookies from your laptop browser:

```bash
python auth.py
```

This will prompt you to:

1. Log into [exploretock.com](https://www.exploretock.com/login) on your **laptop** browser using "Sign in with Google"
2. Open **DevTools** (press `F12` or `Cmd+Opt+I` on Mac)
3. Go to the **Console** tab
4. Paste the JS snippet the script prints — it copies your cookies to clipboard
5. Paste the cookie JSON back into the terminal prompt

Your session is saved to `tock_session/state.json`. Re-run `auth.py` if it expires (usually lasts a few weeks).

## Configuration

Edit `config.py` to set your preferences:

| Setting | Default | Description |
|---------|---------|-------------|
| `PARTY_SIZE` | `2` | Number of guests |
| `PREFERRED_DATES` | Mar 16–22 | Dates to check, in priority order |
| `POLL_INTERVAL_SECONDS` | `1.0` | Seconds between availability checks |
| `PRE_DROP_START_SECONDS` | `30` | Start polling this many seconds before drop |
| `NOTIFY_METHOD` | `"console"` | `"console"`, `"twilio"`, `"telegram"`, or `"pushover"` |
| `HEADLESS` | `True` | Set `False` to watch the browser (needs display) |
| `PROXY_SERVER` | `""` | Set to `"http://fwdproxy:8080"` if needed |

## Usage

### Auto-book at next drop (recommended)

```bash
python book.py
```

The bot will:
- Load the Tock page
- Detect the release time from the "New reservations will be released on..." message
- Sleep until 30 seconds before the drop
- Poll rapidly and grab the first slot

### Book immediately (skip waiting)

```bash
python book.py --now
```

### Dry run (find slot but don't book)

```bash
python book.py --dry-run --now
```

### Monitor availability (recon)

```bash
python recon.py --interval 60 --duration 48
```

Polls every 60 seconds for 48 hours. Logs changes to `recon_log.jsonl`.

## Safety Features

The bot has three layers of protection against duplicate bookings:

1. **File lock** (`booking.lock`) — Only one instance of `book.py` can run at a time. A second instance will exit with an error.
2. **Booking marker** (`booking_confirmed.txt`) — After a successful booking, this file is created. Future runs will refuse to book until you delete it.
3. **In-session guard** — Once a booking succeeds within a single run, the polling loop stops immediately.

To allow a new booking after a previous one:
```bash
rm booking_confirmed.txt
```

## Bot Detection

The bot uses `playwright-stealth` and anti-detection browser flags to avoid Cloudflare challenges. If you still get blocked:

- Check `debug_page.png` and `challenge_stuck.png` for what the bot sees
- Try refreshing your session cookies via `python auth.py`
- The bot waits up to 30 seconds for challenge pages to auto-resolve

## File Overview

| File | Purpose |
|------|---------|
| `book.py` | Main booking bot |
| `recon.py` | Availability monitor / logger |
| `auth.py` | One-time cookie export from laptop browser |
| `config.py` | All configuration (dates, party size, notifications) |
| `notify.py` | Notification backends (console, Twilio, Telegram, Pushover) |
| `environment.yml` | Conda environment definition |

## Notifications

By default, notifications print to console. To get SMS/push alerts:

1. Set `NOTIFY_METHOD` in `config.py` to your preferred service
2. Fill in the corresponding API keys (Twilio, Telegram, or Pushover)
3. Uncomment the relevant pip dependency in `environment.yml` and run `conda env update -f environment.yml`
