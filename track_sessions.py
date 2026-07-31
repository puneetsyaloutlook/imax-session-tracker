"""
Tracks the IMAX Sydney "now showing" page for new sessions and sends a
Discord alert, including the film name and session date/time, when one
appears that wasn't seen on the previous check.

How it works:
1. Fetches the cinema page.
2. Pulls the structured session data out of the page's embedded JSON-LD
   (a script tag the site itself uses for search engines), which includes
   the session ID, film name, and start time for every showing.
3. Compares the current set of session IDs against the IDs saved from the
   last run.
4. Any ID not seen before triggers an alert and gets saved for next time.

Run this on a schedule (cron, GitHub Actions, etc). Every 30 minutes is
a reasonable starting point, no need to go faster than that.
"""

import json
import os
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

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

SYDNEY = ZoneInfo("Australia/Sydney")


def fetch_sessions():
    """
    Returns a dict of {session_id: {"film": ..., "start": <formatted string>}}
    pulled from the page's embedded JSON-LD ScreeningEvent data.
    """
    response = requests.get(CINEMA_URL, headers=HEADERS, timeout=20)
    response.raise_for_status()
    html = response.text

    sessions = {}
    for block in re.finditer(
        r'<script type="application/ld\+json">\s*(\[.*?\])\s*</script>',
        html,
        re.DOTALL,
    ):
        try:
            events = json.loads(block.group(1))
        except json.JSONDecodeError:
            continue

        for event in events:
            if event.get("@type") != "ScreeningEvent":
                continue

            url = event.get("url", "")
            id_match = re.search(r"sessionId=(\d+)", url)
            if not id_match:
                continue

            session_id = id_match.group(1)
            sessions[session_id] = {
                "film": event.get("name", "unknown film"),
                "start": format_session_time(event.get("startDate")),
            }

    return sessions


def format_session_time(iso_string):
    if not iso_string:
        return "unknown time"
    try:
        # Takes the first 19 characters, e.g. "2026-07-31T11:30:00",
        # ignoring fractional seconds and the trailing Z, since the value
        # is always given in UTC.
        dt_utc = datetime.strptime(iso_string[:19], "%Y-%m-%dT%H:%M:%S")
        dt_utc = dt_utc.replace(tzinfo=ZoneInfo("UTC"))
        dt_sydney = dt_utc.astimezone(SYDNEY)
        return dt_sydney.strftime("%A %d %B, %I:%M %p").replace(" 0", " ")
    except ValueError:
        return iso_string


def load_known_ids():
    if STATE_FILE.exists():
        return set(json.loads(STATE_FILE.read_text()))
    return set()


def save_known_ids(ids):
    STATE_FILE.write_text(json.dumps(sorted(ids)))


def send_alert(new_sessions):
    lines = [
        f"{info['film']}, {info['start']}"
        for info in new_sessions.values()
    ]
    message = "New IMAX Sydney session(s):\n" + "\n".join(lines)
    print(message)

    if not DISCORD_WEBHOOK_URL:
        print("Discord webhook URL not set, skipping Discord alert.")
        return

    response = requests.post(DISCORD_WEBHOOK_URL, json={"content": message}, timeout=10)
    response.raise_for_status()


def main():
    sessions = fetch_sessions()
    current_ids = set(sessions.keys())
    known_ids = load_known_ids()

    new_ids = current_ids - known_ids

    if new_ids:
        new_sessions = {sid: sessions[sid] for sid in new_ids}
        send_alert(new_sessions)
    else:
        print("No new sessions.")

    # Only grows the known set, so a session that disappears (e.g. it sold
    # out or the date passed) doesn't get treated as "new" again if it
    # somehow reappears.
    save_known_ids(known_ids | current_ids)


if __name__ == "__main__":
    main()
