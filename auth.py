#!/usr/bin/env python3
"""
One-time auth: import your Tock session cookies from your laptop browser.

Usage:
    1. Log into Tock (exploretock.com) on your laptop via Google
    2. Open DevTools (F12) → Console tab
    3. Paste the JS snippet this script prints and hit Enter
    4. Copy the JSON output
    5. Run: python auth.py
    6. Paste the JSON when prompted
"""

import json
import sys
from pathlib import Path

import config

SESSION_PATH = Path(__file__).parent / config.SESSION_DIR

JS_SNIPPET = r"""
// Run this in DevTools Console on exploretock.com after logging in:
(()=>{const c=document.cookie.split('; ').map(c=>{const[name,...rest]=c.split('=');return{name,value:rest.join('='),domain:'.exploretock.com',path:'/',expires:-1,httpOnly:false,secure:true,sameSite:'None'}});copy(JSON.stringify(c));console.log('Copied '+c.length+' cookies to clipboard!')})()
""".strip()


def import_cookies():
    SESSION_PATH.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("  Fuhuihua — Import Tock Session")
    print("=" * 60)
    print()
    print("Step 1: Log into Tock on your laptop browser:")
    print("        https://www.exploretock.com/login")
    print("        (use 'Sign in with Google')")
    print()
    print("Step 2: After login, open DevTools (F12) → Console")
    print()
    print("Step 3: Paste this JS snippet and press Enter:")
    print()
    print(f"  {JS_SNIPPET}")
    print()
    print("  → It copies the cookies to your clipboard.")
    print()
    print("Step 4: Paste the cookies below (Ctrl+V) and press Enter:")
    print()

    raw = input("> ").strip()

    if not raw:
        print("No input. Aborting.")
        sys.exit(1)

    try:
        cookies = json.loads(raw)
    except json.JSONDecodeError:
        print("Invalid JSON. Make sure you copied the full output.")
        sys.exit(1)

    if not isinstance(cookies, list):
        print("Expected a JSON array of cookies.")
        sys.exit(1)

    # Convert to Playwright storage state format
    pw_cookies = []
    for c in cookies:
        pw_cookies.append({
            "name": c.get("name", ""),
            "value": c.get("value", ""),
            "domain": c.get("domain", ".exploretock.com"),
            "path": c.get("path", "/"),
            "expires": c.get("expires", -1),
            "httpOnly": c.get("httpOnly", False),
            "secure": c.get("secure", True),
            "sameSite": c.get("sameSite", "None"),
        })

    state = {
        "cookies": pw_cookies,
        "origins": [
            {
                "origin": "https://www.exploretock.com",
                "localStorage": [],
            }
        ],
    }

    state_file = SESSION_PATH / "state.json"
    with open(state_file, "w") as f:
        json.dump(state, f, indent=2)

    print(f"\nImported {len(pw_cookies)} cookies → {state_file}")
    print("Session saved. The bot will use this automatically.")
    print("Re-run if your session expires (usually a few weeks).")


if __name__ == "__main__":
    import_cookies()
