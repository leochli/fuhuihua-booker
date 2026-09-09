#!/usr/bin/env python3
"""
Fuhuihua 24/7 booking bot — runs continuously.

Strategy (verified Sep 2026 via Tock page + community posts):
- New reservations drop DAILY around 5:00 PM PT, roughly 6 days out (rolling window).
- BURST mode (a few minutes around 5 PM): hit candidate date URLs directly,
  poll ~1s with jitter, grab the first available seating.
- STEADY mode (all other times): light round-robin polling of candidate dates
  to catch cancellations / newly released dates.
- Prepaid checkout ($258/person + 20% service + tax) needs a saved card in the
  Tock account. Without one, the bot notifies and keeps monitoring (never blocks).

Safety:
  1. File lock (booking.lock) — only one instance books at a time.
  2. Marker file (booking_confirmed.txt) — after a success, the bot exits and
     will not book again until the marker is deleted.
  3. In-session flag — the polling loop stops right after the first booking.

Usage:
    python booker.py            # run forever (24/7 mode)
    python booker.py --once     # single pass over candidate dates, then exit
    python booker.py --dry-run  # find slots but never enter checkout
"""

import argparse
import atexit
import fcntl
import json
import random
import re
import sys
import time
import traceback
from datetime import datetime, timedelta, date
from pathlib import Path

import pytz
from playwright.sync_api import sync_playwright, Page
from playwright_stealth import Stealth

import config
from notify import send_notification

BASE = Path(__file__).parent
SESSION_STATE = BASE / config.SESSION_DIR / "state.json"
LOCK_FILE = BASE / "booking.lock"
BOOKED_MARKER = BASE / "booking_confirmed.txt"
STATUS_FILE = BASE / "status.json"
DEBUG_DIR = BASE / "debug"
TZ = pytz.timezone(config.DROP_TIMEZONE)

SOLD_OUT_PHRASES = [
    "sold out",
    "no availability",
    "fully booked",
    "no tables available",
    "all reservations sold out",
]
CHALLENGE_PHRASES = [
    "security verification",
    "verifies you are not a bot",
    "checking your browser",
    "just a moment",
    "ray id",
    "ddos protection",
]
CONFIRM_PHRASES = ["confirmed", "thank you", "confirmation number", "booking confirmed"]
PAYMENT_PHRASES = ["card number", "enter your card", "payment method", "add a card"]


# --------------------------------------------------------------------------- #
# Logging / status
# --------------------------------------------------------------------------- #
def log(msg: str):
    ts = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S %Z")
    print(f"[{ts}] {msg}", flush=True)


def update_status(**fields):
    try:
        data = {}
        if STATUS_FILE.exists():
            data = json.loads(STATUS_FILE.read_text())
        data.update(fields)
        data["updated_at"] = datetime.now(TZ).isoformat()
        STATUS_FILE.write_text(json.dumps(data, indent=2))
    except Exception as e:
        log(f"status write failed: {e}")


def read_status() -> dict:
    try:
        if STATUS_FILE.exists():
            return json.loads(STATUS_FILE.read_text())
    except Exception:
        pass
    return {}


def notify(title: str, message: str, cooldown_key: str | None = None,
           cooldown_minutes: int = 60):
    """Send a notification, optionally rate-limited by cooldown_key."""
    if cooldown_key:
        st = read_status()
        last = st.get(f"notify_{cooldown_key}")
        if last:
            try:
                last_dt = datetime.fromisoformat(last)
                if datetime.now(TZ) - last_dt < timedelta(minutes=cooldown_minutes):
                    log(f"notification suppressed by cooldown: {title}")
                    return
            except Exception:
                pass
        update_status(**{f"notify_{cooldown_key}": datetime.now(TZ).isoformat()})
    log(f"NOTIFY: {title} — {message}")
    send_notification(title, message)


# --------------------------------------------------------------------------- #
# Lock (single instance)
# --------------------------------------------------------------------------- #
def acquire_lock() -> bool:
    try:
        fd = open(LOCK_FILE, "w")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fd.write(f"PID started at {datetime.now(TZ).isoformat()}\nargs={sys.argv}\n")
        fd.flush()
        acquire_lock._fd = fd
        atexit.register(release_lock)
        return True
    except (IOError, OSError):
        return False


def release_lock():
    fd = getattr(acquire_lock, "_fd", None)
    if fd:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
            fd.close()
        except Exception:
            pass
    try:
        LOCK_FILE.unlink(missing_ok=True)
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# Dates / schedule
# --------------------------------------------------------------------------- #
def today_pt() -> date:
    return datetime.now(TZ).date()


def is_open_day(d: date) -> bool:
    # Fuhuihua is open Wed–Sun (closed Mon/Tue)
    return d.weekday() in (2, 3, 4, 5, 6)


def candidate_dates() -> list[str]:
    """Dates to watch, in priority order."""
    if config.PREFERRED_DATES:
        return list(config.PREFERRED_DATES)
    out = []
    d = today_pt()
    for i in range(config.LOOKAHEAD_DAYS + 1):
        day = d + timedelta(days=i)
        if is_open_day(day):
            out.append(day.isoformat())
    return out


def burst_targets() -> list[str]:
    """Dates most likely to drop at today's 5 PM release."""
    prefs = [d for d in candidate_dates() if d >= (today_pt() + timedelta(days=4)).isoformat()]
    # Prioritize the rolling-window date, then further-out dates
    anchor = today_pt() + timedelta(days=config.ROLLING_WINDOW_DAYS)
    def key(d):
        dd = date.fromisoformat(d)
        return (abs((dd - anchor).days), d)
    return sorted(set(prefs), key=key)


def in_daily_drop_window(now: datetime | None = None) -> bool:
    """The wide window around the known daily 5 PM PT release."""
    now = now or datetime.now(TZ)
    drop = now.replace(hour=config.DROP_HOUR, minute=config.DROP_MINUTE,
                       second=0, microsecond=0)
    start = drop - timedelta(minutes=config.PRE_DROP_START_MINUTES)
    end = drop + timedelta(minutes=config.POST_DROP_END_MINUTES)
    return start <= now <= end


def in_burst_window(now: datetime | None = None) -> bool:
    """True during the daily drop window OR the hourly :59–:01 micro-burst."""
    now = now or datetime.now(TZ)
    if in_daily_drop_window(now):
        return True
    if getattr(config, "HOURLY_BURST", False):
        return now.minute >= 59 or now.minute <= 1
    return False


def seconds_until_burst() -> float:
    now = datetime.now(TZ)
    drop = now.replace(hour=config.DROP_HOUR, minute=config.DROP_MINUTE,
                       second=0, microsecond=0)
    start = drop - timedelta(minutes=config.PRE_DROP_START_MINUTES)
    return (start - now).total_seconds()


# --------------------------------------------------------------------------- #
# Browser
# --------------------------------------------------------------------------- #
def launch_browser(p):
    log("Launching Chromium (stealth)...")
    launch_args = [
        "--disable-blink-features=AutomationControlled",
        "--disable-features=IsolateOrigins,site-per-process",
        "--no-first-run",
        "--no-default-browser-check",
        # The runtime egress proxy MITMs TLS with a custom CA that Chrome
        # doesn't trust; ignore cert errors so pages load through the proxy.
        "--ignore-certificate-errors",
    ]
    kwargs = {
        "headless": config.HEADLESS,
        "slow_mo": config.SLOW_MO,
        "args": launch_args,
    }
    chrome_exe = getattr(config, "CHROME_EXECUTABLE", "")
    if chrome_exe:
        exe_path = BASE / chrome_exe if not chrome_exe.startswith("/") else Path(chrome_exe)
        if exe_path.exists():
            kwargs["executable_path"] = str(exe_path)
            log(f"Using Chrome binary: {exe_path}")
        else:
            log(f"WARNING: CHROME_EXECUTABLE not found ({exe_path}), using bundled browser")
    # Proxy: explicit config wins; otherwise use the runtime's egress proxy from env
    proxy_server = getattr(config, "PROXY_SERVER", "")
    if not proxy_server:
        import os
        from urllib.parse import urlparse
        for var in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
            raw = os.environ.get(var, "")
            if raw:
                proxy_server = raw
                break
    if proxy_server:
        try:
            from urllib.parse import urlparse
            u = urlparse(proxy_server)
            proxy_cfg = {"server": f"{u.scheme}://{u.hostname}:{u.port}"}
            if u.username:
                proxy_cfg["username"] = u.username
            if u.password:
                proxy_cfg["password"] = u.password
            kwargs["proxy"] = proxy_cfg
            log(f"Using proxy: {proxy_cfg['server']}")
        except Exception as e:
            log(f"Proxy parse failed ({e}); continuing without proxy")
    if config.PROXY_SERVER:
        kwargs["proxy"] = {"server": config.PROXY_SERVER}
        log(f"Using proxy: {config.PROXY_SERVER}")
    browser = p.chromium.launch(**kwargs)
    ctx_kwargs = {
        "user_agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "viewport": {"width": 1280, "height": 800},
        "locale": "en-US",
        "timezone_id": config.DROP_TIMEZONE,
    }
    if SESSION_STATE.exists():
        ctx_kwargs["storage_state"] = str(SESSION_STATE)
        log(f"Loaded session: {SESSION_STATE}")
    else:
        log("WARNING: no saved session — checkout will require login. "
            "Import cookies to tock_session/state.json.")
    context = browser.new_context(**ctx_kwargs)
    page = context.new_page()
    Stealth().apply_stealth_sync(page)
    return browser, page


def wait_for_challenge(page: Page, timeout: int = 20) -> bool:
    for i in range(timeout):
        try:
            text = page.inner_text("body").lower()
        except Exception:
            time.sleep(1)
            continue
        if any(p in text for p in CHALLENGE_PHRASES):
            if i % 5 == 0:
                log(f"  bot challenge detected, waiting... ({i}s)")
            time.sleep(1)
        else:
            return True
    log("  WARNING: challenge page did not resolve in time")
    return False


def is_sold_out_text(text: str) -> bool:
    t = text.lower()
    return any(p in t for p in SOLD_OUT_PHRASES)


def session_looks_valid(page: Page) -> bool:
    """Best-effort check that we're still logged in to Tock."""
    try:
        text = page.inner_text("body").lower()
    except Exception:
        return True  # can't tell; don't raise false alarms
    # Tock shows an account menu when logged in; a bare "sign in" link suggests logged out.
    if "sign in" in text and "sign out" not in text:
        return False
    return True


# --------------------------------------------------------------------------- #
# Availability checking
# --------------------------------------------------------------------------- #
def date_url(target_date: str, size: int) -> str:
    base = config.EXPERIENCE_URL or config.TOCK_URL
    return f"{base}?date={target_date}&size={size}"


def available_times(page: Page, target_date: str) -> list[str]:
    """Load a date page and return bookable seating times (e.g. ['5:00 PM'])."""
    url = date_url(target_date, config.PARTY_SIZE)
    log(f"  checking {target_date}: {url}")
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        log(f"  goto failed for {target_date}: {e}")
        return []
    time.sleep(2 + random.uniform(0.3, 1.2))
    if not wait_for_challenge(page, timeout=15):
        page.screenshot(path=str(DEBUG_DIR / f"challenge_{target_date}.png"))
        return []
    time.sleep(1)

    try:
        text = page.inner_text("body")
    except Exception:
        return []
    if is_sold_out_text(text):
        log(f"  {target_date}: sold out / no availability")
        return []

    # Look for clickable time-slot buttons
    times: list[str] = []
    selectors = [
        'button[data-testid="bookable-slot"]',
        'button[class*="TimeSlot"]',
        'button[class*="timeslot"]',
        'button[class*="Slot"]',
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel)
            for i in range(loc.count()):
                btn = loc.nth(i)
                try:
                    if not btn.is_visible(timeout=500) or not btn.is_enabled(timeout=500):
                        continue
                    t = btn.inner_text().strip()
                except Exception:
                    continue
                if re.search(r"\d{1,2}:\d{2}\s*[AP]M", t, re.IGNORECASE):
                    times.append(t)
        except Exception:
            continue

    # Fallback: time-like buttons
    if not times:
        for pat in ["5:00 PM", "8:00 PM", "6:30 PM"]:
            try:
                btn = page.locator(f'button:has-text("{pat}")').first
                if btn.count() and btn.is_visible(timeout=500) and btn.is_enabled(timeout=500):
                    times.append(pat)
            except Exception:
                continue

    times = sorted(set(times), key=lambda t: (
        config.SEATING_PREFERENCE.index(t) if t in config.SEATING_PREFERENCE else 99, t))
    if times:
        log(f"  *** {target_date}: AVAILABLE times {times}")
    return times


def pick_time(times: list[str]) -> str | None:
    for pref in config.SEATING_PREFERENCE:
        for t in times:
            if pref.lower() in t.lower():
                return t
    return times[0] if times else None


# --------------------------------------------------------------------------- #
# Booking flow
# --------------------------------------------------------------------------- #
class BookingBot:
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.booked = False

    def mark_booked(self, details: str = ""):
        self.booked = True
        BOOKED_MARKER.write_text(
            f"Booked at {datetime.now(TZ).isoformat()}\n{details}\n")
        update_status(booked_at=datetime.now(TZ).isoformat(), details=details)
        log(f"BOOKED — marker written: {BOOKED_MARKER}")

    def click_time_slot(self, page: Page, time_text: str) -> bool:
        """Click the chosen seating time on the date page."""
        selectors = [
            f'button[data-testid="bookable-slot"]:has-text("{time_text}")',
            f'button:has-text("{time_text}")',
        ]
        for sel in selectors:
            try:
                btn = page.locator(sel).first
                if btn.count() and btn.is_visible(timeout=2000) and btn.is_enabled(timeout=2000):
                    log(f"Clicking time slot: {time_text}")
                    btn.click()
                    time.sleep(2 + random.uniform(0.5, 1.5))
                    return True
            except Exception as e:
                log(f"  click failed ({sel}): {e}")
        log("Could not click time slot")
        return False

    def complete_checkout(self, page: Page) -> str:
        """Walk Tock's prepaid checkout.

        Returns: 'booked' | 'payment_needed' | 'failed'
        """
        log("Navigating checkout...")
        checkout_buttons = [
            'button:has-text("Add to cart")',
            'button:has-text("Continue")',
            'button:has-text("Book Now")',
            'button:has-text("Reserve")',
            'button:has-text("Checkout")',
            'button:has-text("Book")',
            'button[type="submit"]',
        ]
        pay_buttons = [
            'button:has-text("Complete")',
            'button:has-text("Pay")',
            'button:has-text("Confirm")',
            'button:has-text("Place order")',
        ]

        for click_num in range(8):  # safety limit
            time.sleep(1.5 + random.uniform(0.5, 1.5))
            step = 0

            def shot(name):
                path = DEBUG_DIR / f"checkout_{click_num}_{name}.png"
                try:
                    page.screenshot(path=str(path))
                except Exception:
                    pass

            shot("state")
            try:
                text = page.inner_text("body")
            except Exception as e:
                log(f"  can't read page: {e}")
                return "failed"
            low = text.lower()

            if any(w in low for w in CONFIRM_PHRASES):
                log("BOOKING CONFIRMED!")
                shot("confirmed")
                return "booked"

            if any(w in low for w in PAYMENT_PHRASES):
                log("Payment page reached — looking for saved card...")
                shot("payment")
                clicked_pay = False
                for sel in pay_buttons:
                    try:
                        btn = page.locator(sel).first
                        if btn.count() and btn.is_visible(timeout=2000):
                            log(f"Clicking pay button: {btn.inner_text().strip()}")
                            btn.click()
                            time.sleep(3)
                            clicked_pay = True
                            break
                    except Exception:
                        continue
                if not clicked_pay:
                    log("No saved payment method and no pay button — card needed.")
                    return "payment_needed"
                continue

            clicked = False
            for sel in checkout_buttons:
                try:
                    btn = page.locator(sel).first
                    if btn.count() and btn.is_visible(timeout=1500):
                        log(f"Clicking: {btn.inner_text().strip()}")
                        btn.click()
                        time.sleep(2)
                        clicked = True
                        break
                except Exception:
                    continue
            if not clicked:
                log("No more checkout buttons to click.")
                break

        try:
            low = page.inner_text("body").lower()
        except Exception:
            return "failed"
        if any(w in low for w in CONFIRM_PHRASES):
            log("BOOKING CONFIRMED!")
            return "booked"
        log("Checkout did not complete — no confirmation found.")
        page.screenshot(path=str(DEBUG_DIR / "checkout_incomplete.png"))
        return "failed"

    def try_book(self, page: Page, target_date: str, time_text: str) -> str:
        """Attempt one booking. Returns 'booked' | 'payment_needed' | 'failed'."""
        log(f"=== BOOKING ATTEMPT: {target_date} at {time_text}, "
            f"party of {config.PARTY_SIZE} ===")
        if self.dry_run or config.DRY_RUN:
            notify("DRY RUN: slot found",
                   f"Fuhuihua {target_date} at {time_text} — not booking (dry run).")
            return "failed"

        if not self.click_time_slot(page, time_text):
            return "failed"
        result = self.complete_checkout(page)

        if result == "booked":
            self.mark_booked(
                f"date={target_date} time={time_text} party={config.PARTY_SIZE}")
            notify("BOOKED! Fuhuihua",
                   f"{target_date} at {time_text}, party of {config.PARTY_SIZE}. "
                   f"Check your email/Tock account for confirmation!")
        elif result == "payment_needed":
            notify(
                "Fuhuihua bot: payment needed",
                f"Slot found ({target_date} at {time_text}) but no saved card. "
                f"Book it manually NOW: {date_url(target_date, config.PARTY_SIZE)}",
                cooldown_key="payment_needed",
                cooldown_minutes=config.PAYMENT_NEEDED_COOLDOWN_MINUTES,
            )
        else:
            notify("Fuhuihua bot: checkout failed",
                   f"Slot found ({target_date} at {time_text}) but checkout did not "
                   f"complete. Screenshot saved in debug/.",
                   cooldown_key="checkout_failed",
                   cooldown_minutes=config.ERROR_NOTIFY_COOLDOWN_MINUTES)
        return result


# --------------------------------------------------------------------------- #
# Main loop
# --------------------------------------------------------------------------- #
def run_bot(once: bool = False, dry_run: bool = False):
    bot = BookingBot(dry_run=dry_run)
    DEBUG_DIR.mkdir(exist_ok=True)

    if not dry_run and BOOKED_MARKER.exists():
        log(f"Already booked: {BOOKED_MARKER.read_text().strip()}")
        log("Delete booking_confirmed.txt to allow a new booking.")
        return

    if not acquire_lock():
        log("ERROR: another instance is already running. Exiting.")
        return
    log("Lock acquired.")

    update_status(started_at=datetime.now(TZ).isoformat(),
                  mode="24/7" if not once else "once",
                  dry_run=dry_run)

    with sync_playwright() as p:
        browser, page = launch_browser(p)
        try:
            # Startup sanity: load the main page once
            log(f"Loading {config.TOCK_URL}")
            page.goto(config.TOCK_URL, wait_until="domcontentloaded", timeout=60000)
            time.sleep(3)
            wait_for_challenge(page, timeout=25)
            if not session_looks_valid(page):
                notify("Fuhuihua bot: Tock session may be expired",
                       "The page shows a sign-in prompt. Import fresh cookies to "
                       "tock_session/state.json so checkout can complete.",
                       cooldown_key="session_expired",
                       cooldown_minutes=360)
            else:
                log("Session looks OK.")

            if once:
                _single_pass(bot, page)
                return

            rr_index = 0  # round-robin cursor for steady polling
            burst_done_for: str | None = None  # date string of last burst day
            consec_errors = 0

            while True:
                if bot.booked:
                    log("Booking completed — exiting (marker file set).")
                    break

                try:
                    today = today_pt().isoformat()
                    if in_burst_window():
                        # Notify only for the daily 5 PM drop, not every hourly micro-burst
                        if in_daily_drop_window() and burst_done_for != today:
                            burst_done_for = today
                            notify("Fuhuihua bot: drop window open",
                                   "5 PM release window — polling aggressively.",
                                   cooldown_key=f"burst_{today}",
                                   cooldown_minutes=30)
                        _burst_pass(bot, page)
                        if bot.booked:
                            break
                        time.sleep(config.BURST_POLL_SECONDS + random.uniform(0, 0.8))
                    else:
                        dates = candidate_dates()
                        if dates:
                            target = dates[rr_index % len(dates)]
                            rr_index += 1
                            times = available_times(page, target)
                            if times:
                                picked = pick_time(times)
                                result = bot.try_book(page, target, picked)
                                if result == "booked":
                                    break
                                if result == "payment_needed":
                                    # Keep monitoring; user may book manually
                                    time.sleep(60)
                                    continue
                        else:
                            log("No candidate dates configured.")
                        consec_errors = 0
                        wait_s = config.STEADY_POLL_SECONDS + random.uniform(-20, 40)
                        wait_s = max(45, wait_s)
                        # Sleep in chunks so burst window entry is prompt
                        _sleep_interruptible(wait_s)

                    # Hourly heartbeat in status
                    update_status(last_check=datetime.now(TZ).isoformat(),
                                  booked=bot.booked)

                except Exception as e:
                    consec_errors += 1
                    log(f"ERROR in main loop ({consec_errors}x): {e}")
                    log(traceback.format_exc(limit=5))
                    notify("Fuhuihua bot error", str(e)[:300],
                           cooldown_key="loop_error",
                           cooldown_minutes=config.ERROR_NOTIFY_COOLDOWN_MINUTES)
                    backoff = min(60 * consec_errors, 600)
                    log(f"Backing off {backoff}s...")
                    time.sleep(backoff)
                    # Refresh the page context on repeated errors
                    if consec_errors >= 3:
                        log("Too many errors — reloading browser context.")
                        try:
                            browser.close()
                        except Exception:
                            pass
                        browser, page = launch_browser(p)
                        consec_errors = 0
        finally:
            try:
                browser.close()
            except Exception:
                pass
            release_lock()
            log("Bot stopped.")


def _single_pass(bot: BookingBot, page: Page):
    """One pass over candidate dates (for --once / testing)."""
    for target in candidate_dates():
        times = available_times(page, target)
        if times:
            picked = pick_time(times)
            result = bot.try_book(page, target, picked)
            log(f"single pass: {target} -> {result}")
            if result == "booked":
                break
        if bot.booked:
            break
    log("Single pass complete.")


def _burst_pass(bot: BookingBot, page: Page):
    """One aggressive round over the likeliest drop dates."""
    targets = burst_targets()
    log(f"Burst round over: {targets}")
    for target in targets:
        if bot.booked:
            return
        times = available_times(page, target)
        if times:
            picked = pick_time(times)
            result = bot.try_book(page, target, picked)
            if result == "booked":
                return
            # If payment is needed, keep trying other dates but don't spam
            if result == "payment_needed":
                continue


def _sleep_interruptible(total_seconds: float):
    """Sleep in small chunks so we enter the burst window on time."""
    end = time.time() + total_seconds
    while time.time() < end:
        if in_burst_window():
            log("Drop window approaching — switching to burst mode.")
            return
        time.sleep(min(15, end - time.time()))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fuhuihua 24/7 booking bot")
    parser.add_argument("--once", action="store_true",
                        help="Single pass over candidate dates, then exit")
    parser.add_argument("--dry-run", action="store_true",
                        help="Find slots but never enter checkout")
    args = parser.parse_args()
    run_bot(once=args.once, dry_run=args.dry_run)
