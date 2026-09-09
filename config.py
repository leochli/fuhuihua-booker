# Fuhuihua Booking Bot — 24/7 configuration
# Strategy (verified Sep 2026 via Tock page + community posts):
# - New reservations drop DAILY around 5:00 PM PT, roughly 6 days out (rolling window).
# - Trick: at 4:59 PM open the date URL directly, refresh at 5:00 PM sharp, pay immediately.
# - Hourly micro-burst: from :59 to :01 of EVERY hour the bot polls aggressively
#   to catch cancellations / surprise drops (in addition to the 5 PM window).
# - Prepaid: $258/person + 20% service charge (+ SF tax). A saved card in the Tock
#   account is REQUIRED for the bot to complete checkout on its own.

# Tock URLs
TOCK_URL = "https://www.exploretock.com/fui-hui-hua-san-francisco/"
# Direct experience page (observed Sep 2026; bot falls back to TOCK_URL if it changes)
EXPERIENCE_URL = (
    "https://www.exploretock.com/fui-hui-hua-san-francisco/"
    "experience/559289/winters-depth-spring-approaches-experience"
)

# Booking preferences
PARTY_SIZE = 2
# Preferred dates (YYYY-MM-DD), in priority order. Empty list = any date.
PREFERRED_DATES = []
# How many days ahead to consider (restaurant is open Wed–Sun)
LOOKAHEAD_DAYS = 14
# Seating preference, in order (Fuhuihua seatings: 5:00 PM and 8:00 PM)
SEATING_PREFERENCE = ["5:00 PM", "8:00 PM"]

# Drop schedule (America/Los_Angeles)
DROP_HOUR = 17
DROP_MINUTE = 0
DROP_TIMEZONE = "America/Los_Angeles"
ROLLING_WINDOW_DAYS = 6  # new dates appear ~6 days out
# Burst mode: aggressive polling from this many minutes before the drop...
PRE_DROP_START_MINUTES = 3
# ...until this many minutes after the drop
POST_DROP_END_MINUTES = 6
BURST_POLL_SECONDS = 1.0  # seconds between checks during burst

# Hourly micro-burst: near EVERY hour, from :59 to :01, poll aggressively to
# catch cancellations / surprise drops. The wider 17:00 window above stays
# because that's the known daily release.
HOURLY_BURST = True

# Steady mode: light polling for cancellations / newly released dates
STEADY_POLL_SECONDS = 120  # check one date every ~2 min (round-robin)

# Auth: Google OAuth can't be automated, so a Tock session is imported once.
# The session is stored at tock_session/state.json (see README-MUSE.md).
SESSION_DIR = "tock_session"

# Notification settings
NOTIFY_METHOD = "console"  # Options: "console", "twilio", "telegram", "pushover"
# NOTE: for 24/7 runs, the operator (Muse) relays booking alerts to the user.

# Twilio (SMS)
TWILIO_ACCOUNT_SID = ""
TWILIO_AUTH_TOKEN = ""
TWILIO_FROM_NUMBER = ""
TWILIO_TO_NUMBER = ""

# Telegram
TELEGRAM_BOT_TOKEN = ""
TELEGRAM_CHAT_ID = ""

# Pushover
PUSHOVER_USER_KEY = ""
PUSHOVER_APP_TOKEN = ""

# Browser settings
HEADLESS = True
SLOW_MO = 0
USE_CHROMIUM = True  # Chromium + stealth (no Cloudflare challenge observed on Tock)
# Path to a Chrome/Chromium binary. Empty = let Playwright use its bundled browser.
CHROME_EXECUTABLE = ""
PROXY_SERVER = ""  # e.g. "http://fwdproxy:8080" if needed

# Safety / behavior
DRY_RUN = False  # True = find slots but never click through checkout
MAX_BOOKING_ATTEMPTS_PER_SLOT = 1  # stop after first real booking attempt
PAYMENT_NEEDED_COOLDOWN_MINUTES = 45  # don't spam when no card is saved
ERROR_NOTIFY_COOLDOWN_MINUTES = 60
