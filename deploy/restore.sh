#!/bin/sh
# Restore the demo stack from deploy/backup.sh output.
#
#   sh deploy/restore.sh backups/clip-<timestamp>.sql.gz [backups/clip-<timestamp>-uploads.tar.gz]
#
# Replaces everything in the database with the backup, so it asks first. The
# backend is stopped while it runs, so no open connection holds a lock the
# restore needs, and any class in progress ends. The restore is one
# transaction: if it fails, the database is left as it was.
set -eu

if [ $# -lt 1 ]; then
    echo "usage: sh deploy/restore.sh <dump.sql.gz> [uploads.tar.gz]" >&2
    exit 2
fi

# Make the backup paths absolute before moving to the repository root.
absolute() { case "$1" in /*) echo "$1" ;; *) echo "$(pwd)/$1" ;; esac; }
DUMP=$(absolute "$1")
UPLOADS=""
[ $# -ge 2 ] && UPLOADS=$(absolute "$2")
cd "$(dirname "$0")/.."

[ -s "$DUMP" ] || { echo "No dump at $DUMP" >&2; exit 2; }
if [ -n "$UPLOADS" ] && [ ! -s "$UPLOADS" ]; then
    echo "No uploads archive at $UPLOADS" >&2
    exit 2
fi

PROJECT=${CLIP_DEMO_PROJECT:-clip-demo}
COMPOSE="docker compose -p $PROJECT -f docker-compose.demo.yml --env-file deploy/demo.env"

printf "This replaces the demo database with %s and stops the backend while it runs. Type restore to go on: " "$DUMP"
read -r answer
[ "$answer" = "restore" ] || { echo "Nothing changed."; exit 1; }

restart() { echo "Starting the backend..."; $COMPOSE start backend; }

# Restart only when the database and uploads match. The database step is one
# transaction, so a failure there leaves the old database and is safe to restart.
# A failure after the database was restored leaves the backend stopped.
STAGE=stopping
on_exit() {
    status=$?
    if [ "$status" -eq 0 ] || [ "$STAGE" = "stopping" ] || [ "$STAGE" = "database" ]; then
        [ "$status" -eq 0 ] || echo "Restore FAILED during the $STAGE step; the database is unchanged." >&2
        restart
    else
        echo "WARNING: the database was restored but the uploads were not." >&2
        echo "The backend is left STOPPED so it does not run with files that do not match the database." >&2
        echo "Fix the uploads archive and run this script again, or start it anyway with:" >&2
        echo "  $COMPOSE start backend" >&2
    fi
}
trap on_exit EXIT

echo "Stopping the backend..."
$COMPOSE stop backend

STAGE=database
echo "Restoring the database..."
gunzip -c "$DUMP" | $COMPOSE exec -T db psql -U clip -d clip -v ON_ERROR_STOP=1 -q --single-transaction

STAGE=uploads
if [ -n "$UPLOADS" ]; then
    echo "Restoring uploaded material..."
    # The backend is stopped, so the files go in through a one-off container
    # with the same volume.
    $COMPOSE run --rm -T --no-deps --entrypoint tar backend -C /data -xzf - < "$UPLOADS"
fi

STAGE=done
echo "Done."
