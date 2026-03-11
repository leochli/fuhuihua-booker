#!/usr/bin/env python3
"""
One-time auth: opens a browser so you can log into Tock via Google,
then saves the session (cookies + localStorage) for the bot to reuse.

Usage:
    python auth.py

A browser window will open. Log into Tock with Google. Once you see your
account page, press Enter in the terminal to save the session and close.
"""

from pathlib import Path

from playwright.sync_api import sync_playwright

import config


SESSION_PATH = Path(__file__).parent / config.SESSION_DIR


def save_session():
    print("Opening browser — please log into Tock with your Google account.")
    print()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)  # Must be visible for OAuth
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )
        page = context.new_page()

        # Navigate to Tock login
        page.goto("https://www.exploretock.com/login", wait_until="networkidle")

        print("=" * 50)
        print("  1. Click 'Sign in with Google'")
        print("  2. Complete the Google login flow")
        print("  3. Wait until you see your Tock account/dashboard")
        print("  4. Come back here and press ENTER to save")
        print("=" * 50)

        input("\nPress ENTER after you're logged in...")

        # Save the full browser state (cookies, localStorage, etc.)
        context.storage_state(path=str(SESSION_PATH / "state.json"))
        SESSION_PATH.mkdir(parents=True, exist_ok=True)
        context.storage_state(path=str(SESSION_PATH / "state.json"))

        print(f"\nSession saved to {SESSION_PATH / 'state.json'}")
        print("The bot will reuse this session. You shouldn't need to do this again")
        print("unless your session expires (typically a few weeks).")

        browser.close()


if __name__ == "__main__":
    save_session()
