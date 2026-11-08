#!/bin/sh
# Restore the demo stack from deploy/backup.sh output.
#
#   sh deploy/restore.sh backups/clip-<timestamp>.sql.gz [backups/clip-<timestamp>-uploads.tar.gz]
#
# Replaces everything in the database with the backup, so it asks first.
# Run it with no class in progress: live sessions are held in the backend's
# memory and are not in the dump.
set -eu

if [ $# -lt 1 ]; then
    echo "usage: sh deploy/restore.sh <dump.sql.gz> [uploads.tar.gz]" >&2
    exit 2
fi

PROJECT=${CLIP_DEMO_PROJECT:-clip-demo}
COMPOSE="docker compose -p $PROJECT -f docker-compose.demo.yml --env-file deploy/demo.env"

printf "This replaces the demo database with %s. Type restore to go on: " "$1"
read -r answer
[ "$answer" = "restore" ] || { echo "Nothing changed."; exit 1; }

echo "Restoring the database..."
gunzip -c "$1" | $COMPOSE exec -T db psql -U clip -d clip -v ON_ERROR_STOP=1 -q

if [ $# -ge 2 ]; then
    echo "Restoring uploaded material..."
    $COMPOSE exec -T backend tar -C /data -xzf - < "$2"
fi

echo "Restarting the backend so it reads the restored data..."
$COMPOSE restart backend
echo "Done."
