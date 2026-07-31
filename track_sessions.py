"""
Tracks the IMAX Sydney "now showing" page for new session IDs and sends
an alert when one appears that wasn't seen on the previous check.

How it works:
1. Fetches the cinema page.
2. Pulls out every sessionId from the booking links on the page.
3. Compares that set against the IDs saved from the last run.
4. Any ID not seen before triggers an alert and gets saved for next time.

Run this on a schedule (cron, GitHub Actions, etc). Every 30 minutes is
a reasonable starting point, no need to go faster than that.
"""

import json
import os
import re
from pathlib import Path

import requests

CINEMA_URL = "https://www.eventcinemas.com.au/Cinema/IMAX-Sydney"
STATE_FILE = Path(__file__).parent / "known_sessions.json"

# Set this as an environment variable or repo secret, don't paste it here.
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")

# A normal browser user-agent, some sites block requests without one.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}


def fetch_session_ids():
    response = requests.get(CINEMA_URL, headers=HEADERS, timeout=20)
    response.raise_for_status()
    # Session IDs appear in booking links like ?sessionId=15434269
    ids = re.findall(r"sessionId=(\d+)", response.text)
    return set(ids)


def debug_dump_context():
    """
    Temporary helper, not used by the normal alert flow. Prints a chunk
    of raw HTML around the first sessionId it finds, so we can see what
    surrounds it (dates, times, etc are likely nearby as data attributes
    or JSON, even if not visible as plain text on the page).
    """
    response = requests.get(CINEMA_URL, headers=HEADERS, timeout=20)
    response.raise_for_status()
    match = re.search(r"sessionId=\d+", response.text)
    if not match:
        print("No sessionId found in the page at all.")
        return
    start = max(0, match.start() - 1500)
    end = min(len(response.text), match.end() + 500)
    print(response.text[start:end])


def load_known_ids():
    if STATE_FILE.exists():
        return set(json.loads(STATE_FILE.read_text()))
    return set()


def save_known_ids(ids):
    STATE_FILE.write_text(json.dumps(sorted(ids)))


def send_alert(new_ids):
    message = f"New IMAX Sydney session(s) for The Odyssey: {', '.join(new_ids)}"
    print(message)

    if not DISCORD_WEBHOOK_URL:
        print("Discord webhook URL not set, skipping Discord alert.")
        return

    response = requests.post(DISCORD_WEBHOOK_URL, json={"content": message}, timeout=10)
    response.raise_for_status()


def main():
    current_ids = fetch_session_ids()
    known_ids = load_known_ids()

    new_ids = current_ids - known_ids

    if new_ids:
        send_alert(new_ids)
    else:
        print("No new sessions.")

    # Only grows the known set, so a session that disappears (e.g. it sold
    # out or the date passed) doesn't get treated as "new" again if it
    # somehow reappears.
    save_known_ids(known_ids | current_ids)


if __name__ == "__main__":
    debug_dump_context()
    # main()
