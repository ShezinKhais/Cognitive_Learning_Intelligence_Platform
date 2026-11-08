#!/bin/sh
# Back up the demo stack: the database and the uploaded material.
#
#   sh deploy/backup.sh [output-directory]
#
# Writes <dir>/clip-<timestamp>.sql.gz and <dir>/clip-<timestamp>-uploads.tar.gz
# (default dir: ./backups, which git ignores). The stack keeps running: pg_dump
# reads a consistent snapshot, and uploads are only ever added or purged.
# Restore with deploy/restore.sh. The files hold personal data; keep them
# somewhere only the people running the demo can read.
set -eu

PROJECT=${CLIP_DEMO_PROJECT:-clip-demo}
COMPOSE="docker compose -p $PROJECT -f docker-compose.demo.yml --env-file deploy/demo.env"
OUT=${1:-backups}
STAMP=$(date -u +%Y%m%dT%H%M%SZ)

mkdir -p "$OUT"
umask 077

echo "Dumping the database..."
$COMPOSE exec -T db pg_dump -U clip -d clip --clean --if-exists --no-owner \
    | gzip > "$OUT/clip-$STAMP.sql.gz"

echo "Copying uploaded material..."
$COMPOSE exec -T backend tar -C /data -czf - uploads > "$OUT/clip-$STAMP-uploads.tar.gz"

echo "Done:"
ls -l "$OUT/clip-$STAMP.sql.gz" "$OUT/clip-$STAMP-uploads.tar.gz"
