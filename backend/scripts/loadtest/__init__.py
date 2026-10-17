"""Load, reconnect and failure-recovery tests against a real server.

Owner: General CS, Phase 8.

    python -m scripts.loadtest --out ../docs/load-test-results.json

Run from backend/, with Postgres up. It starts the backend as its own
process, in production mode, against a database it creates and drops, so it
exercises what a deployment runs: stored users and consent, the real
WebSocket endpoint, the real scheduler. Nothing in the development database
is touched. See docs/load-and-recovery.md for what each scenario checks.
"""
