#!/usr/bin/env python3
"""
One-time auth: log into Tock via Google and save the session for the bot.

On a headless server (no display), this launches a headless Chromium with
a remote debugging port. You port-forward from your laptop and complete
the Google login in your local Chrome.

Usage:
    # On the server:
    python auth.py

    # On your laptop (in another terminal):
    ssh -L 9222:localhost:9222 your-devserver

    # Then open in your local Chrome:
    chrome://inspect/#devices
    → Configure → add localhost:9222
    → Click "inspect" on the Tock tab
    → Complete Google login in the DevTools window
    → Come back to the server terminal and press Enter
"""

import json
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

import config


SESSION_PATH = Path(__file__).parent / config.SESSION_DIR
DEBUG_PORT = 9222


def save_session():
    SESSION_PATH.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("  Fuhuihua — Tock Login (Headless Server Mode)")
    print("=" * 60)
    print()
    print(f"Launching headless browser with remote debugging on port {DEBUG_PORT}...")
    print()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                f"--remote-debugging-port={DEBUG_PORT}",
                "--remote-debugging-address=0.0.0.0",
            ],
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

        # Navigate to Tock login
        page.goto("https://www.exploretock.com/login", wait_until="networkidle")

        print("Browser is running. Now on your LAPTOP:\n")
        print("  1. Port-forward in a new terminal:")
        print(f"     ssh -L {DEBUG_PORT}:localhost:{DEBUG_PORT} $(hostname)")
        print()
        print("  2. Open Chrome on your laptop and go to:")
        print("     chrome://inspect/#devices")
        print()
        print(f'  3. Click "Configure" → add "localhost:{DEBUG_PORT}"')
        print('  4. You should see the Tock page listed — click "inspect"')
        print("  5. In the DevTools window, click 'Sign in with Google'")
        print("     and complete the login flow")
        print("  6. Once you're logged in and see the Tock dashboard,")
        print("     come back HERE and press Enter")
        print()
        print("-" * 60)

        input("Press ENTER after you've logged in via DevTools... ")

        # Save the full browser state (cookies, localStorage, etc.)
        state_file = SESSION_PATH / "state.json"
        context.storage_state(path=str(state_file))

        print(f"\nSession saved to {state_file}")
        print("The bot will reuse this session automatically.")
        print("Re-run this script if your session expires (usually a few weeks).")

        browser.close()


if __name__ == "__main__":
    save_session()
