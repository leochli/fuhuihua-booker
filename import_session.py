#!/usr/bin/env python3
"""
Import Tock session cookies (exported from your laptop browser) into
Playwright storage state, non-interactively.

Usage:
    1. Log into https://www.exploretock.com/login on your laptop (Google login).
    2. Open DevTools (F12) -> Console, paste this and hit Enter
       (it copies the cookies to your clipboard):

       (()=>{const c=document.cookie.split('; ').map(c=>{const[name,...rest]=c.split('=');return{name,value:rest.join('='),domain:'.exploretock.com',path:'/',expires:-1,httpOnly:false,secure:true,sameSite:'None'}});copy(JSON.stringify(c));console.log('Copied '+c.length+' cookies!')})()

    3. Save the clipboard content to tock_cookies.json and give the file to Muse,
       then run:
           python import_session.py tock_cookies.json
"""
import json
import sys
from pathlib import Path

import config

SESSION_PATH = Path(__file__).parent / config.SESSION_DIR


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    raw = Path(sys.argv[1]).read_text().strip()
    cookies = json.loads(raw)
    if not isinstance(cookies, list):
        print("Expected a JSON array of cookies.")
        sys.exit(1)

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
        "origins": [{"origin": "https://www.exploretock.com", "localStorage": []}],
    }
    SESSION_PATH.mkdir(parents=True, exist_ok=True)
    state_file = SESSION_PATH / "state.json"
    state_file.write_text(json.dumps(state, indent=2))
    print(f"Imported {len(pw_cookies)} cookies -> {state_file}")


if __name__ == "__main__":
    main()
