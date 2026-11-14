"""Compare the deployed web and API revision with a known build, without credentials."""

import argparse
import json
import re
from urllib.request import urlopen


def read_json(base: str, path: str) -> dict:
    with urlopen(base.rstrip("/") + path, timeout=10) as response:
        if "no-store" not in response.headers.get("Cache-Control", ""):
            raise RuntimeError(f"{path} must be served without caching.")
        return json.load(response)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--revision", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-f0-9]{40}", args.revision):
        parser.error("Use the full git commit for the expected revision.")
    for path in ("/release.json", "/api/v1/health"):
        if read_json(args.base, path).get("release_sha") != args.revision:
            raise SystemExit(f"{path} does not match the expected release.")
    print(f"Web and API match {args.revision}")


if __name__ == "__main__":
    main()
