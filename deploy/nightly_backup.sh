#!/bin/sh
# Nightly: back up the demo stack, encrypt the new files, remove the plaintext,
# and drop backups older than 30 days.
# Key: ~/.clip-backup-key (never committed; override with CLIP_BACKUP_KEY).
# Off-site upload of the .enc files is manual.
# Any failure exits non-zero and keeps the plaintext, so a backup is never lost.
set -eu
cd "$(dirname "$0")/.."
KEY=${CLIP_BACKUP_KEY:-$HOME/.clip-backup-key}
[ -s "$KEY" ] || { echo "Nightly backup FAILED: no key at $KEY" >&2; exit 1; }

sh deploy/backup.sh

for f in $(ls -t backups/clip-*.sql.gz | head -1) $(ls -t backups/clip-*-uploads.tar.gz | head -1); do
    tmp="$f.enc.tmp"
    if ! openssl enc -aes-256-cbc -pbkdf2 -salt -pass file:"$KEY" -in "$f" -out "$tmp"; then
        rm -f "$tmp"
        echo "Nightly backup FAILED: could not encrypt $f (plaintext kept)" >&2
        exit 1
    fi
    if ! openssl enc -d -aes-256-cbc -pbkdf2 -pass file:"$KEY" -in "$tmp" | cmp -s - "$f"; then
        rm -f "$tmp"
        echo "Nightly backup FAILED: encrypted copy of $f does not decrypt (plaintext kept)" >&2
        exit 1
    fi
    chmod 600 "$tmp"
    mv "$tmp" "$f.enc"
    rm -f "$f"
done

find backups -name 'clip-*' -mtime +30 -delete
echo "Nightly backup finished $(date -u +%Y-%m-%dT%H:%M:%SZ)"