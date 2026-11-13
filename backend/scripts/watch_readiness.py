"""Poll the existing readiness endpoint from outside the application.

    python scripts/watch_readiness.py https://host/api/v1/ready [--webhook URL]

Alerts once when two checks in a row fail, and once when the server reports
an error spike (at least ten server errors a minute for two minutes), and
says when each recovers. Messages go to standard output, and to an incoming
webhook too when one is given (Teams and Slack both accept {"text": ...}).
The webhook address can also come from CLIP_ALERT_WEBHOOK, which keeps it
out of the process list. Neither the endpoint URL, the response body nor
the webhook address is ever printed or sent.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

INTERVAL_SECONDS = 30
FAILURES_BEFORE_ALERT = 2

DOWN = "ALERT: C.L.I.P is not ready. Check the web proxy, API and database."
UP = "RECOVERED: C.L.I.P readiness checks are passing again."
SPIKE = "ALERT: C.L.I.P is logging server errors at a high rate. See System status, Recent errors."
CALM = "RECOVERED: C.L.I.P server errors are back to a normal rate."


# Whether the last readiness answer reported an error spike. Kept beside
# ready() rather than returned from it, so ready() stays a plain yes or no.
last_spike = False


def ready(url: str) -> bool:
    """An unreachable or unreadable endpoint is not ready."""
    global last_spike
    last_spike = False
    try:
        with urlopen(url, timeout=8) as response:
            body = json.load(response)
            last_spike = bool(body.get("server_error_spike"))
            return response.status == 200 and body.get("ready") is True
    except (OSError, URLError, ValueError, AttributeError):
        return False


def notify(message: str, webhook: str | None) -> None:
    print(message, flush=True)
    if not webhook:
        return
    data = json.dumps({"text": message}).encode()
    try:
        urlopen(
            Request(webhook, data=data, headers={"Content-Type": "application/json"}),
            timeout=8,
        ).close()
    except (OSError, URLError, ValueError):
        # The address may hold a secret token, so it is never printed.
        print("WARNING: the alert webhook could not be reached.", flush=True)


class Watch:
    """What to say after each check. Kept apart from the loop so it can be
    tested without waiting."""

    def __init__(self) -> None:
        self.failures = 0
        self.spiking = False

    def step(self, is_ready: bool, spike: bool) -> list[str]:
        said = []
        if is_ready:
            if self.failures >= FAILURES_BEFORE_ALERT:
                said.append(UP)
            self.failures = 0
        else:
            self.failures += 1
            if self.failures == FAILURES_BEFORE_ALERT:
                said.append(DOWN)
        # Only a server that answers can say it is spiking.
        if is_ready and spike and not self.spiking:
            said.append(SPIKE)
            self.spiking = True
        elif is_ready and not spike and self.spiking:
            said.append(CALM)
            self.spiking = False
        return said


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="Full deployment readiness URL ending in /api/v1/ready")
    parser.add_argument("--webhook", help="Incoming webhook for alerts (or CLIP_ALERT_WEBHOOK)")
    args = parser.parse_args()
    webhook = args.webhook or os.environ.get("CLIP_ALERT_WEBHOOK") or None

    watch = Watch()
    while True:
        is_ready = ready(args.url)
        for message in watch.step(is_ready, is_ready and last_spike):
            notify(message, webhook)
        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
