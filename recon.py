#!/usr/bin/env python3
"""
Recon script: monitors Fuhuihua's Tock page to detect when new reservations drop.
Run this for a few days to learn the exact release schedule before deploying the bot.

Usage:
    python recon.py [--interval 60] [--duration 48]
"""

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

from config import TOCK_URL, PARTY_SIZE, HEADLESS, PROXY_SERVER


LOG_FILE = Path(__file__).parent / "recon_log.jsonl"


def get_availability(page) -> dict:
    """Load the Tock page and extract available dates/times."""
    page.goto(TOCK_URL, wait_until="domcontentloaded", timeout=30000)
    time.sleep(2)  # Let dynamic content settle

    # Try to set party size if selector exists
    try:
        party_selector = page.locator('[data-testid="party-size-selector"]')
        if party_selector.is_visible(timeout=3000):
            party_selector.click()
            option = page.locator(f'text="{PARTY_SIZE}"')
            if option.is_visible(timeout=2000):
                option.click()
                time.sleep(1)
    except Exception:
        pass

    # Collect available slots
    slots = []
    try:
        # Tock typically renders availability as clickable time buttons
        # These selectors may need adjustment after initial recon
        time_buttons = page.locator(
            'button[class*="time"], '
            '[data-testid*="time"], '
            '[class*="Slot"], '
            '[class*="slot"], '
            'a[href*="book"]'
        )
        count = time_buttons.count()
        for i in range(count):
            btn = time_buttons.nth(i)
            text = btn.inner_text().strip()
            if text:
                slots.append(text)
    except Exception:
        pass

    # Also grab any "sold out" or "no availability" messages
    page_text = page.inner_text("body")
    no_avail = any(
        phrase in page_text.lower()
        for phrase in ["sold out", "no availability", "fully booked", "no tables"]
    )

    return {
        "slots": slots,
        "no_availability_detected": no_avail,
        "page_title": page.title(),
    }


def log_entry(data: dict):
    """Append a timestamped entry to the log file."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "local_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        **data,
    }
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def run_recon(interval_seconds: int, duration_hours: float):
    """Poll the Tock page at regular intervals and log changes."""
    print(f"Starting recon — polling every {interval_seconds}s for {duration_hours}h")
    print(f"Logging to: {LOG_FILE}")
    print(f"URL: {TOCK_URL}")
    print(f"Party size: {PARTY_SIZE}")
    print("-" * 60)

    end_time = time.time() + (duration_hours * 3600)
    prev_slots = None

    with sync_playwright() as p:
        launch_kwargs = {"headless": HEADLESS}
        if PROXY_SERVER:
            launch_kwargs["proxy"] = {"server": PROXY_SERVER}
        browser = p.chromium.launch(**launch_kwargs)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        )
        page = context.new_page()

        while time.time() < end_time:
            try:
                data = get_availability(page)
                entry = log_entry(data)

                # Detect changes
                current_slots = set(data["slots"])
                if prev_slots is not None and current_slots != prev_slots:
                    new_slots = current_slots - prev_slots
                    if new_slots:
                        print(f"*** NEW SLOTS DETECTED at {entry['local_time']}:")
                        for s in new_slots:
                            print(f"    {s}")
                        log_entry({"event": "NEW_SLOTS", "new_slots": list(new_slots)})

                prev_slots = current_slots

                status = "available" if data["slots"] else "none"
                print(
                    f"[{entry['local_time']}] "
                    f"Slots: {len(data['slots'])} ({status}) | "
                    f"No-avail msg: {data['no_availability_detected']}"
                )

            except Exception as e:
                print(f"[ERROR] {e}")
                log_entry({"error": str(e)})

            time.sleep(interval_seconds)

        browser.close()

    print("\nRecon complete. Analyze results with:")
    print(f"  python -c \"import json; [print(json.loads(l)) for l in open('{LOG_FILE}')]\"")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fuhuihua Tock recon")
    parser.add_argument("--interval", type=int, default=60, help="Poll interval in seconds")
    parser.add_argument("--duration", type=float, default=48, help="Duration in hours")
    args = parser.parse_args()

    run_recon(args.interval, args.duration)
