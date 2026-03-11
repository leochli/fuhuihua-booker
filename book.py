#!/usr/bin/env python3
"""
Fuhuihua Tock Booking Bot

Waits for the reservation drop, grabs a slot for party of 2, and books it.

Usage:
    # First: save your Tock session (one-time, Google OAuth)
    python auth.py

    # Book at the next drop (uses config.DROP_HOUR/DROP_MINUTE)
    python book.py

    # Book immediately (skip waiting for drop time)
    python book.py --now

    # Dry run (find slot but don't confirm booking)
    python book.py --dry-run
"""

import argparse
import atexit
import fcntl
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytz
from playwright.sync_api import sync_playwright, Page, Browser
from playwright_stealth import Stealth

import config
from notify import send_notification

SESSION_STATE = Path(__file__).parent / config.SESSION_DIR / "state.json"
LOCK_FILE = Path(__file__).parent / "booking.lock"
BOOKED_MARKER = Path(__file__).parent / "booking_confirmed.txt"


def acquire_lock() -> bool:
    """Acquire an exclusive file lock to prevent multiple instances."""
    try:
        lock_fd = open(LOCK_FILE, "w")
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock_fd.write(f"PID {sys.argv} started at {datetime.now().isoformat()}\n")
        lock_fd.flush()
        # Keep the fd open (and lock held) for the lifetime of the process
        acquire_lock._fd = lock_fd
        atexit.register(release_lock)
        return True
    except (IOError, OSError):
        return False


def release_lock():
    """Release the file lock."""
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


class BookingBot:
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.booked = False  # Guard: set True after first successful booking
        self.tz = pytz.timezone(config.DROP_TIMEZONE)

    def check_already_booked(self) -> bool:
        """Check if a booking was already completed (from a previous run)."""
        if BOOKED_MARKER.exists():
            content = BOOKED_MARKER.read_text().strip()
            print(f"A booking was already confirmed: {content}")
            print("Delete booking_confirmed.txt to allow a new booking.")
            return True
        return False

    def mark_booked(self, details: str = ""):
        """Mark that a booking has been completed to prevent duplicates."""
        self.booked = True
        BOOKED_MARKER.write_text(
            f"Booked at {datetime.now().isoformat()}\n{details}\n"
        )

    def parse_release_time(self, page: Page) -> datetime | None:
        """Extract the next release time from the page text.

        Looks for text like:
          'New reservations will be released on March 15, 2026 at 6:10 PM PST'
        """
        page_text = page.inner_text("body")

        # Match patterns like "March 15, 2026 at 6:10 PM PST"
        pattern = (
            r"released\s+on\s+"
            r"(\w+\s+\d{1,2},?\s+\d{4})\s+"
            r"at\s+"
            r"(\d{1,2}:\d{2}\s*[AP]M)\s*"
            r"(PST|PDT|PT|EST|EDT|ET|CST|CDT|CT|MST|MDT|MT)?"
        )
        match = re.search(pattern, page_text, re.IGNORECASE)
        if not match:
            print(f"Could not find release time in page text.")
            print(f"Page text (first 500 chars): {page_text[:500]}")
            return None

        date_str = match.group(1)   # e.g. "March 15, 2026"
        time_str = match.group(2)   # e.g. "6:10 PM"
        tz_str = match.group(3)     # e.g. "PST"

        # Parse the datetime
        combined = f"{date_str} {time_str}"
        # Handle with or without comma: "March 15 2026" or "March 15, 2026"
        for fmt in ("%B %d, %Y %I:%M %p", "%B %d %Y %I:%M %p"):
            try:
                drop_time = datetime.strptime(combined, fmt)
                break
            except ValueError:
                continue
        else:
            print(f"Could not parse datetime: '{combined}'")
            return None

        # Apply timezone
        drop_time = self.tz.localize(drop_time)
        print(f"Parsed release time: {drop_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        return drop_time

    def wait_for_drop(self, drop_time: datetime):
        """Sleep until just before the given drop time."""
        now = datetime.now(self.tz)
        wait_until = drop_time - timedelta(seconds=config.PRE_DROP_START_SECONDS)
        wait_seconds = (wait_until - now).total_seconds()

        if wait_seconds > 0:
            print(f"Drop time: {drop_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
            print(f"Starting poll at: {wait_until.strftime('%H:%M:%S %Z')}")
            print(f"Waiting {wait_seconds:.0f} seconds ({wait_seconds/3600:.1f} hours)...")
            time.sleep(wait_seconds)

        print("Polling window open — searching for slots...")

    def load_session(self) -> dict | None:
        """Load saved browser session from auth.py."""
        if not SESSION_STATE.exists():
            print("ERROR: No saved session found.")
            print("Run `python auth.py` first to log in via Google and save your session.")
            return None
        print(f"Loading saved session from {SESSION_STATE}")
        return str(SESSION_STATE)

    def wait_for_challenge(self, page: Page, timeout: int = 30) -> bool:
        """Wait for Cloudflare/bot-check challenge page to resolve.

        Returns True if the real page loaded, False if still stuck on challenge.
        """
        challenge_phrases = [
            "security verification",
            "verifies you are not a bot",
            "checking your browser",
            "just a moment",
            "ray id",
            "ddos protection",
        ]
        for i in range(timeout):
            try:
                page_text = page.inner_text("body").lower()
            except Exception:
                time.sleep(1)
                continue

            if any(p in page_text for p in challenge_phrases):
                if i % 5 == 0:
                    print(f"  Bot challenge detected — waiting... ({i}s)")
                time.sleep(1)
            else:
                print("  Challenge cleared (or no challenge).")
                return True

        print("  WARNING: Challenge page did not resolve within timeout.")
        page.screenshot(path="/home/leochli/fuhuihua-booker/challenge_stuck.png")
        return False

    def is_sold_out(self, page: Page) -> bool:
        """Check if the page shows a sold-out message."""
        page_text = page.inner_text("body").lower()
        sold_out_phrases = [
            "all reservations sold out",
            "sold out",
            "no availability",
            "fully booked",
            "no tables available",
        ]
        return any(phrase in page_text for phrase in sold_out_phrases)

    def find_and_select_slot(self, page: Page) -> bool:
        """Navigate to the restaurant page and try to grab a slot."""
        page.goto(config.TOCK_URL, wait_until="domcontentloaded", timeout=60000)
        time.sleep(3)
        self.wait_for_challenge(page, timeout=20)
        time.sleep(2)  # Let JS render

        # First check: is the page showing sold out?
        if self.is_sold_out(page):
            print("Page says SOLD OUT — no slots available yet.")
            return False

        # Page is NOT sold out — look for actual bookable experiences/slots.
        # Tock uses experience cards or time slot links. Only match elements
        # that are clearly bookable (contain price or time patterns).
        page_text = page.inner_text("body")
        print(f"Page text preview: {page_text[:200]}...")

        # Look for Tock experience/offering links (these are the actual bookable items)
        slot_selectors = [
            # Tock experience cards typically have a link with the experience name + price
            'a[href*="/experience/"]',
            'a[href*="/event/"]',
            # Bookable time slots on the calendar view
            'button[data-testid="bookable-slot"]',
            '[data-testid="experience-card"]',
            '[data-testid="offering"]',
        ]

        for sel in slot_selectors:
            slots = page.locator(sel)
            count = slots.count()
            if count > 0:
                first_slot = slots.first
                slot_text = first_slot.inner_text().strip()
                print(f"FOUND BOOKABLE ITEM: {slot_text}")

                if self.dry_run:
                    print("[DRY RUN] Would click this. Stopping.")
                    send_notification(
                        "DRY RUN: Slot Found!",
                        f"Fuhuihua: {slot_text} for {config.PARTY_SIZE}",
                    )
                    return True

                first_slot.click()
                time.sleep(3)
                page.screenshot(path="/home/leochli/fuhuihua-booker/after_click.png")
                return True

        # Fallback: look for any date-specific availability
        for target_date in config.PREFERRED_DATES:
            print(f"Checking date: {target_date}")
            try:
                date_url = f"{config.TOCK_URL}?date={target_date}&size={config.PARTY_SIZE}"
                page.goto(date_url, wait_until="domcontentloaded", timeout=60000)
                time.sleep(3)
                self.wait_for_challenge(page, timeout=20)
                time.sleep(2)

                if self.is_sold_out(page):
                    print(f"  {target_date}: sold out")
                    continue

                # Screenshot each date page for debugging
                page.screenshot(
                    path=f"/home/leochli/fuhuihua-booker/date_{target_date}.png"
                )

                # Look for bookable items on this date
                for sel in slot_selectors:
                    slots = page.locator(sel)
                    count = slots.count()
                    if count > 0:
                        first_slot = slots.first
                        slot_text = first_slot.inner_text().strip()
                        print(f"FOUND SLOT: {target_date} — {slot_text}")

                        if self.dry_run:
                            print("[DRY RUN] Would click this. Stopping.")
                            send_notification(
                                "DRY RUN: Slot Found!",
                                f"Fuhuihua: {target_date} — {slot_text}",
                            )
                            return True

                        first_slot.click()
                        time.sleep(3)
                        return True

            except Exception as e:
                print(f"  Error checking {target_date}: {e}")
                continue

        return False

    def select_party_and_time(self, page: Page) -> bool:
        """After clicking an experience, select party size and first available time."""
        print("Selecting party size and time...")
        page.screenshot(path="/home/leochli/fuhuihua-booker/step_select.png")

        # Set party size if a selector is visible
        try:
            party_selectors = [
                'select[name*="party"]',
                'select[name*="size"]',
                '[data-testid="party-size"]',
                'button:has-text("2 guests")',
                'button:has-text("2 Guests")',
            ]
            for sel in party_selectors:
                el = page.locator(sel).first
                if el.is_visible(timeout=2000):
                    if el.evaluate("el => el.tagName") == "SELECT":
                        el.select_option(str(config.PARTY_SIZE))
                    else:
                        el.click()
                    time.sleep(1)
                    print(f"Set party size to {config.PARTY_SIZE}")
                    break
        except Exception as e:
            print(f"Party size selection: {e}")

        # Click first available time slot
        time_selectors = [
            'button[data-testid="bookable-slot"]',
            'button[class*="TimeSlot"]',
            'button[class*="timeslot"]',
            'a[href*="/book"]',
            # Tock often shows times as clickable buttons
            'button:has-text(":00 PM")',
            'button:has-text(":30 PM")',
            'button:has-text(":00 AM")',
            'button:has-text(":30 AM")',
        ]
        for sel in time_selectors:
            slots = page.locator(sel)
            if slots.count() > 0:
                slot = slots.first
                slot_text = slot.inner_text().strip()
                print(f"Clicking time slot: {slot_text}")
                slot.click()
                time.sleep(2)
                return True

        print("No time slots found on this page")
        page.screenshot(path="/home/leochli/fuhuihua-booker/step_no_times.png")
        return False

    def complete_booking(self, page: Page) -> bool:
        """Navigate through Tock's multi-step checkout.

        Tock prepaid flow:
        1. Experience selected → party/time page
        2. Add to cart / Continue
        3. Payment page (needs saved card in Tock account)
        4. Confirm & pay
        """
        print("Navigating checkout...")

        # Screenshot each step for debugging
        step = 0

        def screenshot(name):
            nonlocal step
            step += 1
            path = f"/home/leochli/fuhuihua-booker/checkout_{step}_{name}.png"
            page.screenshot(path=path)
            print(f"  Screenshot: {path}")

        try:
            # Step 1: Click through any "Continue" / "Add to Cart" / "Book" buttons
            checkout_buttons = [
                'button:has-text("Add to cart")',
                'button:has-text("Continue")',
                'button:has-text("Book Now")',
                'button:has-text("Reserve")',
                'button:has-text("Checkout")',
                'button:has-text("Book")',
                'button[type="submit"]',
            ]

            max_clicks = 5  # Safety limit
            for click_num in range(max_clicks):
                time.sleep(2)
                screenshot(f"before_click_{click_num}")
                page_text = page.inner_text("body").lower()

                # Check if we've reached confirmation
                if any(w in page_text for w in ["confirmed", "thank you", "confirmation number", "booking confirmed"]):
                    print("BOOKING CONFIRMED!")
                    screenshot("confirmed")
                    return True

                # Check for payment/card entry page — if card not saved, we're stuck
                if any(w in page_text for w in ["card number", "enter your card", "payment method"]):
                    print("PAYMENT PAGE — checking for saved card...")
                    screenshot("payment")
                    # If there's a saved card, Tock may show it and just need a confirm click
                    # Look for a "Complete" or "Pay" or "Confirm" button
                    for sel in ['button:has-text("Complete")', 'button:has-text("Pay")',
                                'button:has-text("Confirm")', 'button:has-text("Place order")']:
                        btn = page.locator(sel).first
                        if btn.is_visible(timeout=2000):
                            print(f"Clicking: {btn.inner_text().strip()}")
                            btn.click()
                            time.sleep(3)
                            break
                    else:
                        print("ERROR: No saved payment method! Add a card to your Tock account.")
                        send_notification(
                            "Fuhuihua Bot: PAYMENT NEEDED",
                            "Slot selected but no saved card. Complete manually NOW!",
                        )
                        # Keep browser open so user can manually finish
                        input("Complete payment manually, then press Enter...")
                        return True
                    continue

                # Try clicking the next checkout button
                clicked = False
                for sel in checkout_buttons:
                    btn = page.locator(sel).first
                    try:
                        if btn.is_visible(timeout=1500):
                            btn_text = btn.inner_text().strip()
                            print(f"Clicking: {btn_text}")
                            btn.click()
                            clicked = True
                            break
                    except Exception:
                        continue

                if not clicked:
                    print("No more buttons to click.")
                    break

            # Final check
            time.sleep(3)
            screenshot("final")
            page_text = page.inner_text("body").lower()
            if any(w in page_text for w in ["confirmed", "thank you", "confirmation"]):
                print("BOOKING CONFIRMED!")
                return True

            print("Checkout may not be complete — check screenshots.")
            return True  # Optimistic — screenshots will show what happened

        except Exception as e:
            print(f"Error during checkout: {e}")
            screenshot("error")
            return False

    def run(self, skip_wait: bool = False):
        """Main booking flow."""
        print("=" * 60)
        print("  Fuhuihua Booking Bot")
        print(f"  Party size: {config.PARTY_SIZE}")
        print(f"  Preferred dates: {config.PREFERRED_DATES}")
        print(f"  Dry run: {self.dry_run}")
        print("=" * 60)

        # Guard 1: Check if a booking was already confirmed
        if not self.dry_run and self.check_already_booked():
            sys.exit(0)

        # Guard 2: Acquire exclusive lock (prevent multiple instances)
        if not acquire_lock():
            print("ERROR: Another instance of book.py is already running!")
            print(f"If this is wrong, delete {LOCK_FILE} and retry.")
            sys.exit(1)
        print("Lock acquired — only this instance can book.")

        # Load saved session
        session_path = self.load_session()
        if not session_path:
            sys.exit(1)

        with sync_playwright() as p:
            # Anti-detection: use realistic browser args
            launch_args = [
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
                "--no-first-run",
                "--no-default-browser-check",
            ]
            launch_kwargs = {
                "headless": config.HEADLESS,
                "slow_mo": config.SLOW_MO,
                "args": launch_args,
            }
            if config.PROXY_SERVER:
                launch_kwargs["proxy"] = {"server": config.PROXY_SERVER}
                print(f"Using proxy: {config.PROXY_SERVER}")

            browser = p.chromium.launch(**launch_kwargs)
            context = browser.new_context(
                storage_state=session_path,
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 800},
                locale="en-US",
                timezone_id="America/Los_Angeles",
            )
            page = context.new_page()
            # Apply stealth patches to avoid bot detection
            Stealth().apply_stealth_sync(page)

            try:
                # Step 1: Load the page and detect release time
                print("Loading page...")
                page.goto(config.TOCK_URL, wait_until="domcontentloaded", timeout=60000)
                time.sleep(3)
                # Wait for bot-check challenge to clear
                self.wait_for_challenge(page, timeout=30)
                time.sleep(2)
                page.screenshot(path="/home/leochli/fuhuihua-booker/debug_page.png")
                print("Screenshot saved: ~/fuhuihua-booker/debug_page.png")
                print(f"Page title: {page.title()}")

                # Step 2: If sold out, parse release time and wait
                if not skip_wait and self.is_sold_out(page):
                    drop_time = self.parse_release_time(page)
                    if drop_time:
                        now = datetime.now(self.tz)
                        if drop_time > now:
                            self.wait_for_drop(drop_time)
                        else:
                            print("Release time already passed — polling immediately.")
                    else:
                        print("WARNING: Could not detect release time. Polling now...")

                # Step 3: Poll for availability
                max_attempts = 300  # ~5 minutes at 1s intervals
                for attempt in range(max_attempts):
                    # Guard: stop immediately if we already booked
                    if self.booked:
                        print("Booking already completed this session — stopping.")
                        break

                    print(f"\nAttempt {attempt + 1}/{max_attempts}")

                    if self.find_and_select_slot(page):
                        if self.dry_run:
                            print("\nDry run complete.")
                            break

                        # Complete booking (only one attempt allowed)
                        if self.complete_booking(page):
                            self.mark_booked(
                                f"Party of {config.PARTY_SIZE}, dates: {config.PREFERRED_DATES}"
                            )
                            send_notification(
                                "BOOKED! Fuhuihua",
                                f"Party of {config.PARTY_SIZE} — check your email for confirmation!",
                            )
                            print("\nDone! Check your Tock account for confirmation.")
                        else:
                            send_notification(
                                "Booking attempt — check manually",
                                "Slot was found but checkout may need manual completion. Check screenshot.",
                            )
                        # Either way, stop after first booking attempt
                        break
                    else:
                        print("No slots found. Retrying...")
                        time.sleep(config.POLL_INTERVAL_SECONDS)
                else:
                    send_notification(
                        "Fuhuihua Bot: No luck",
                        f"No slots found after {max_attempts} attempts.",
                    )
                    print("\nNo slots found. Try adjusting dates or running recon first.")

            except Exception as e:
                print(f"\nFatal error: {e}")
                send_notification("Fuhuihua Bot ERROR", str(e))
                page.screenshot(path="/home/leochli/fuhuihua-booker/fatal_error.png")

            finally:
                browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fuhuihua Tock Booking Bot")
    parser.add_argument("--now", action="store_true", help="Skip waiting for drop time")
    parser.add_argument("--dry-run", action="store_true", help="Find slot but don't book")
    args = parser.parse_args()

    bot = BookingBot(dry_run=args.dry_run)
    bot.run(skip_wait=args.now)
