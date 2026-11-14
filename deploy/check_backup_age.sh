#!/bin/sh
# Alert when no non-empty encrypted database backup is newer than MAX_AGE_HOURS (default 26).
# Exit 0 = fresh, 1 = stale/missing/empty.
# Alerts go to stderr, so cron mails them to MAILTO. Optional: set ALERT_WEBHOOK_URL
# (e.g. a Teams incoming webhook) to also POST the alert. macOS shows a notification too.
set -eu
cd "$(dirname "$0")/.."
DIR=${1:-backups}
MAX_AGE_HOURS=${MAX_AGE_HOURS:-26}
MINUTES=$((MAX_AGE_HOURS * 60))
FRESH=$(find "$DIR" -name 'clip-*.sql.gz.enc' -size +0 -mmin -"$MINUTES" 2>/dev/null | head -1)
if [ -z "$FRESH" ]; then
    MSG="C.L.I.P backup STALE: no non-empty encrypted database backup in $DIR within $MAX_AGE_HOURS hours"
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) ALERT $MSG" >&2
    if [ -n "${ALERT_WEBHOOK_URL:-}" ]; then
        curl -fsS -m 10 -H 'Content-Type: application/json' -d "{\"text\": \"$MSG\"}" "$ALERT_WEBHOOK_URL" >/dev/null \
            || echo "Webhook alert failed" >&2
    fi
    command -v osascript >/dev/null && osascript -e "display notification \"$MSG\" with title \"C.L.I.P backup\"" || true
    exit 1
fi
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) OK newest fresh backup: $FRESH"