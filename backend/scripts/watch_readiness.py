"""Poll the existing readiness endpoint from outside the application."""

from __future__ import annotations

import argparse
import json
import time
from urllib.error import URLError
from urllib.request import urlopen

INTERVAL_SECONDS = 30
FAILURES_BEFORE_ALERT = 2


def ready(url: str) -> bool:
    try:
        with urlopen(url, timeout=8) as response:
            return response.status == 200 and json.load(response).get("ready") is True
    except (OSError, URLError, ValueError, AttributeError):
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="Full deployment readiness URL ending in /api/v1/ready")
    args = parser.parse_args()

    failures = 0
    while True:
        if ready(args.url):
            if failures >= FAILURES_BEFORE_ALERT:
                print("RECOVERED: C.L.I.P readiness checks are passing again.", flush=True)
            failures = 0
        else:
            failures += 1
            if failures == FAILURES_BEFORE_ALERT:
                print(
                    "ALERT: C.L.I.P is not ready. Check the web proxy, API and database.",
                    flush=True,
                )
        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
