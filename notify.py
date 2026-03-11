"""Notification module — alerts you when a booking succeeds or fails."""

import config


def send_notification(title: str, message: str):
    """Send a notification via the configured method."""
    method = config.NOTIFY_METHOD.lower()

    if method == "console":
        _notify_console(title, message)
    elif method == "twilio":
        _notify_twilio(title, message)
    elif method == "telegram":
        _notify_telegram(title, message)
    elif method == "pushover":
        _notify_pushover(title, message)
    else:
        _notify_console(title, message)


def _notify_console(title: str, message: str):
    print(f"\n{'=' * 50}")
    print(f"  {title}")
    print(f"  {message}")
    print(f"{'=' * 50}\n")


def _notify_twilio(title: str, message: str):
    try:
        from twilio.rest import Client

        client = Client(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN)
        client.messages.create(
            body=f"{title}\n{message}",
            from_=config.TWILIO_FROM_NUMBER,
            to=config.TWILIO_TO_NUMBER,
        )
        print(f"SMS sent to {config.TWILIO_TO_NUMBER}")
    except Exception as e:
        print(f"Twilio notification failed: {e}")
        _notify_console(title, message)


def _notify_telegram(title: str, message: str):
    try:
        import requests

        url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, json={
            "chat_id": config.TELEGRAM_CHAT_ID,
            "text": f"*{title}*\n{message}",
            "parse_mode": "Markdown",
        }, timeout=10)
        print("Telegram notification sent")
    except Exception as e:
        print(f"Telegram notification failed: {e}")
        _notify_console(title, message)


def _notify_pushover(title: str, message: str):
    try:
        import requests

        requests.post("https://api.pushover.net/1/messages.json", data={
            "token": config.PUSHOVER_APP_TOKEN,
            "user": config.PUSHOVER_USER_KEY,
            "title": title,
            "message": message,
            "priority": 1,
        }, timeout=10)
        print("Pushover notification sent")
    except Exception as e:
        print(f"Pushover notification failed: {e}")
        _notify_console(title, message)
