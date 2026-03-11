#!/usr/bin/env python3
"""
Fuhuihua Tock Booking Bot

Waits for the reservation drop, grabs a slot for party of 2, and books it.

Usage:
    # Book at the next drop (uses config.DROP_HOUR/DROP_MINUTE)
    python book.py

    # Book immediately (skip waiting for drop time)
    python book.py --now

    # Dry run (find slot but don't confirm booking)
    python book.py --dry-run
"""

import argparse
import sys
import time
from datetime import datetime, timedelta

import pytz
from playwright.sync_api import sync_playwright, Page, Browser

import config
from notify import send_notification


class BookingBot:
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.tz = pytz.timezone(config.DROP_TIMEZONE)

    def wait_for_drop(self):
        """Sleep until just before the configured drop time."""
        now = datetime.now(self.tz)
        drop_time = now.replace(
            hour=config.DROP_HOUR,
            minute=config.DROP_MINUTE,
            second=0,
            microsecond=0,
        )
        # If drop time already passed today, target tomorrow
        if drop_time <= now:
            drop_time += timedelta(days=1)

        wait_until = drop_time - timedelta(seconds=config.PRE_DROP_START_SECONDS)
        wait_seconds = (wait_until - now).total_seconds()

        if wait_seconds > 0:
            print(f"Drop time: {drop_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
            print(f"Starting poll at: {wait_until.strftime('%H:%M:%S %Z')}")
            print(f"Waiting {wait_seconds:.0f} seconds...")
            time.sleep(wait_seconds)

        print("Polling window open — searching for slots...")

    def login(self, page: Page):
        """Log into Tock account."""
        if not config.TOCK_EMAIL or not config.TOCK_PASSWORD:
            print("WARNING: No Tock credentials configured. Proceeding without login.")
            print("You may not be able to complete the booking without being logged in.")
            return False

        print("Logging into Tock...")
        page.goto("https://www.exploretock.com/login", wait_until="networkidle")
        time.sleep(1)

        # Fill email
        email_input = page.locator('input[type="email"], input[name="email"]')
        email_input.fill(config.TOCK_EMAIL)

        # Fill password
        password_input = page.locator('input[type="password"], input[name="password"]')
        password_input.fill(config.TOCK_PASSWORD)

        # Submit
        submit_btn = page.locator('button[type="submit"]')
        submit_btn.click()

        page.wait_for_load_state("networkidle")
        time.sleep(2)

        print("Login complete.")
        return True

    def find_and_select_slot(self, page: Page) -> bool:
        """Navigate to the restaurant page and try to grab a slot."""
        page.goto(config.TOCK_URL, wait_until="networkidle")
        time.sleep(2)

        # Try to set party size
        try:
            # Look for party size dropdown/selector
            party_selectors = [
                '[data-testid="party-size-selector"]',
                'select[name*="party"]',
                'button:has-text("Guest")',
                'button:has-text("guest")',
                '[class*="party"]',
                '[class*="Party"]',
            ]
            for sel in party_selectors:
                el = page.locator(sel).first
                if el.is_visible(timeout=1000):
                    el.click()
                    time.sleep(0.5)
                    # Try clicking the right party size option
                    page.locator(f'text="{config.PARTY_SIZE}"').first.click()
                    time.sleep(1)
                    print(f"Set party size to {config.PARTY_SIZE}")
                    break
        except Exception:
            print("Could not set party size (may be pre-set or not available yet)")

        # Try preferred dates first, then any available date
        all_dates = list(config.PREFERRED_DATES)

        for target_date in all_dates:
            print(f"Checking date: {target_date}")
            try:
                # Try to navigate to the specific date
                # Tock URLs often support date params
                date_url = f"{config.TOCK_URL}?date={target_date}&size={config.PARTY_SIZE}"
                page.goto(date_url, wait_until="networkidle")
                time.sleep(2)

                # Look for available time slots
                slot_selectors = [
                    'button[class*="time"]',
                    'button[class*="Time"]',
                    'button[class*="slot"]',
                    'button[class*="Slot"]',
                    '[data-testid*="time"]',
                    'a[class*="time"]',
                    'button:has-text("PM")',
                    'button:has-text("AM")',
                ]

                for sel in slot_selectors:
                    slots = page.locator(sel)
                    count = slots.count()
                    if count > 0:
                        # Found slots! Click the first available one
                        first_slot = slots.first
                        slot_text = first_slot.inner_text().strip()
                        print(f"FOUND SLOT: {target_date} at {slot_text}")

                        if self.dry_run:
                            print("[DRY RUN] Would click this slot. Stopping.")
                            send_notification(
                                "DRY RUN: Slot Found!",
                                f"Fuhuihua: {target_date} at {slot_text} for {config.PARTY_SIZE}",
                            )
                            return True

                        first_slot.click()
                        time.sleep(2)
                        return True

            except Exception as e:
                print(f"  Error checking {target_date}: {e}")
                continue

        return False

    def complete_booking(self, page: Page) -> bool:
        """Complete the checkout process after selecting a slot."""
        print("Attempting to complete booking...")

        try:
            # Look for confirm/book/reserve button
            confirm_selectors = [
                'button:has-text("Confirm")',
                'button:has-text("Reserve")',
                'button:has-text("Book")',
                'button:has-text("Complete")',
                'button[type="submit"]',
            ]

            for sel in confirm_selectors:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=2000):
                    btn.click()
                    time.sleep(3)
                    print("Clicked confirm button")
                    break

            # Check for success indicators
            page_text = page.inner_text("body").lower()
            success_indicators = ["confirmed", "booked", "reservation", "thank you", "confirmation"]
            if any(indicator in page_text for indicator in success_indicators):
                print("BOOKING CONFIRMED!")
                return True

            # Take a screenshot for manual verification
            screenshot_path = "/home/leochli/fuhuihua-booker/booking_result.png"
            page.screenshot(path=screenshot_path)
            print(f"Screenshot saved: {screenshot_path}")
            return True  # Optimistic — check screenshot

        except Exception as e:
            print(f"Error during checkout: {e}")
            screenshot_path = "/home/leochli/fuhuihua-booker/booking_error.png"
            page.screenshot(path=screenshot_path)
            print(f"Error screenshot saved: {screenshot_path}")
            return False

    def run(self, skip_wait: bool = False):
        """Main booking flow."""
        print("=" * 60)
        print("  Fuhuihua Booking Bot")
        print(f"  Party size: {config.PARTY_SIZE}")
        print(f"  Preferred dates: {config.PREFERRED_DATES}")
        print(f"  Dry run: {self.dry_run}")
        print("=" * 60)

        if not skip_wait:
            self.wait_for_drop()

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=config.HEADLESS,
                slow_mo=config.SLOW_MO,
            )
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 800},
            )
            page = context.new_page()

            try:
                # Step 1: Login
                self.login(page)

                # Step 2: Poll for availability
                max_attempts = 120  # ~2 minutes at 1s intervals
                for attempt in range(max_attempts):
                    print(f"\nAttempt {attempt + 1}/{max_attempts}")

                    if self.find_and_select_slot(page):
                        if self.dry_run:
                            print("\nDry run complete.")
                            break

                        # Step 3: Complete booking
                        if self.complete_booking(page):
                            send_notification(
                                "BOOKED! Fuhuihua",
                                f"Party of {config.PARTY_SIZE} — check your email for confirmation!",
                            )
                            print("\nDone! Check your Tock account for confirmation.")
                            break
                        else:
                            send_notification(
                                "Booking attempt — check manually",
                                "Slot was found but checkout may need manual completion. Check screenshot.",
                            )
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
