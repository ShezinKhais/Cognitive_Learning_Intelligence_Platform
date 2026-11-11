   #!/bin/sh
   # Alert when the newest database backup is missing or older than MAX_AGE_HOURS (default 26).
   # Exit 0 = fresh, 1 = stale/missing, so a monitor can also use the exit code.
   set -eu
   cd "$(dirname "$0")/.."
   DIR=${1:-backups}
   MAX_AGE_HOURS=${MAX_AGE_HOURS:-26}
   MINUTES=$((MAX_AGE_HOURS * 60))
   FRESH=$(find "$DIR" -name 'clip-*.sql.gz' -mmin -"$MINUTES" 2>/dev/null | head -1)
   if [ -z "$FRESH" ]; then
       MSG="C.L.I.P backup STALE: no database backup in $DIR within $MAX_AGE_HOURS hours"
       echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) ALERT $MSG"
       osascript -e "display notification \"$MSG\" with title \"C.L.I.P backup\"" 2>/dev/null || true
       exit 1
   fi
   echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) OK newest fresh backup: $FRESH"