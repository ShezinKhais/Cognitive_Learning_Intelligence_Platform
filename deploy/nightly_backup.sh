   #!/bin/sh
   # Nightly: back up the demo stack, encrypt the new files, drop backups older than 30 days.
   # Key: ~/.clip-backup-key (never committed). Off-site upload of the .enc files is manual.
   set -eu
   cd "$(dirname "$0")/.."
   sh deploy/backup.sh
   for f in $(ls -t backups/clip-*.gz | head -2); do
       openssl enc -aes-256-cbc -pbkdf2 -salt -pass file:"$HOME/.clip-backup-key" -in "$f" -out "$f.enc"
       chmod 600 "$f.enc"
   done
   find backups -name 'clip-*' -mtime +30 -delete
   echo "Nightly backup finished $(date -u +%Y-%m-%dT%H:%M:%SZ)"