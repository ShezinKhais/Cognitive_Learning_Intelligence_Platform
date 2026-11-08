#!/bin/sh
# Back up the demo stack: the database and the uploaded material.
#
#   sh deploy/backup.sh [output-directory]
#
# Writes <dir>/clip-<timestamp>.sql.gz and <dir>/clip-<timestamp>-uploads.tar.gz
# (default dir: ./backups at the repository root, which git ignores). The stack
# keeps running: pg_dump reads a consistent snapshot, and uploads are only ever
# added or purged. Restore with deploy/restore.sh. The files hold personal
# data; keep them somewhere only the people running the demo can read.
set -eu

# Paths below are relative to the repository root, wherever this is run from.
OUT=${1:-backups}
case "$OUT" in /*) ;; *) OUT="$(pwd)/$OUT" ;; esac
cd "$(dirname "$0")/.."

PROJECT=${CLIP_DEMO_PROJECT:-clip-demo}
COMPOSE="docker compose -p $PROJECT -f docker-compose.demo.yml --env-file deploy/demo.env"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
DUMP="$OUT/clip-$STAMP.sql.gz"
UPLOADS="$OUT/clip-$STAMP-uploads.tar.gz"

umask 077
mkdir -p "$OUT"

# A plain pipe would report gzip's success even when pg_dump failed, leaving
# an empty backup that looks fine. Each step writes a file and is checked.
fail() {
    rm -f "$DUMP" "$DUMP.sql" "$UPLOADS"
    echo "Backup failed: $1" >&2
    exit 1
}

echo "Dumping the database..."
$COMPOSE exec -T db pg_dump -U clip -d clip --clean --if-exists --no-owner > "$DUMP.sql" \
    || fail "pg_dump did not finish. Is the stack running?"
[ -s "$DUMP.sql" ] || fail "pg_dump wrote nothing."
gzip -c "$DUMP.sql" > "$DUMP" || fail "could not compress the dump."
rm -f "$DUMP.sql"

echo "Copying uploaded material..."
$COMPOSE exec -T backend tar -C /data -czf - uploads > "$UPLOADS" \
    || fail "could not copy the uploads."

echo "Done:"
ls -l "$DUMP" "$UPLOADS"
