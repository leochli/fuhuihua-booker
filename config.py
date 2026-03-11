# Fuhuihua Booking Bot Configuration

# Tock URL
TOCK_URL = "https://www.exploretock.com/fui-hui-hua-san-francisco/"

# Booking preferences
PARTY_SIZE = 2
# Preferred dates (YYYY-MM-DD). Bot tries in order, takes first available.
PREFERRED_DATES = [
    "2026-03-16",  # Mon
    "2026-03-17",  # Tue
    "2026-03-18",  # Wed
    "2026-03-19",  # Thu
    "2026-03-20",  # Fri
    "2026-03-21",  # Sat
    "2026-03-22",  # Sun
]
# If no preferred dates available, accept any date within this many days
FLEXIBLE_DAYS = 30

# Auth: Google OAuth login is handled via saved browser session.
# Run `python auth.py` once to log in manually and save your session.
SESSION_DIR = "tock_session"

# Polling
POLL_INTERVAL_SECONDS = 1.0  # How often to check for availability
PRE_DROP_START_SECONDS = 30  # Start polling this many seconds before expected drop

# Expected drop time (24h format, PT). Adjust after recon.
# Common Tock drop times: midnight, 10am, noon
DROP_HOUR = 0
DROP_MINUTE = 0
DROP_TIMEZONE = "America/Los_Angeles"

# Notification settings (pick one or more)
NOTIFY_METHOD = "console"  # Options: "console", "twilio", "telegram", "pushover"

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
HEADLESS = True  # Set False to watch the browser in action
SLOW_MO = 0  # Milliseconds to slow down actions (for debugging)
