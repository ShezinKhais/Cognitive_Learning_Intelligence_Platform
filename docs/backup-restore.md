# Backups and restore
## Which tool to use

| Deployment | Back up / restore with | What it covers |
|---|---|---|
| Docker demo stack (`docker-compose.demo.yml`) | `deploy/backup.sh`, `deploy/restore.sh`, nightly `deploy/nightly_backup.sh` | Main database and uploaded material. **Not** the history database: the demo stack does not run one. |
| Source checkout with PostgreSQL client tools, or any setup with `HISTORY_DATABASE_URL` set | `backend/scripts/database_backup.py` (below) | Main database, plus the history database when `HISTORY_DATABASE_URL` is set. Not the uploads. |

If a deployment enables the history database, back it up with `database_backup.py`; `deploy/backup.sh` alone would miss it.
Owner: BBIS, Phase 7. Code: `backend/scripts/database_backup.py`.

## Taking a backup

From `backend/`, with the usual `.env`:

    python scripts/database_backup.py backup --out backups --keep 30

This dumps the main database, and the history database when `HISTORY_DATABASE_URL` is
set, to `backups/clip-<time>.dump` and `backups/clip_history-<time>.dump`, then keeps the
newest 30 of each. Run it once a day from the host's scheduler (cron or a systemd timer).
It needs the PostgreSQL client tools (`pg_dump`, `pg_restore`, `createdb`), best of
the same major version as the database server. A newer client works: its extra
`transaction_timeout` setting is the one restore error the script accepts.

A dump is created readable by its owner only, and `backups/` is git-ignored. Store the
folder on an encrypted volume and copy it off the machine: a backup on the same disk is
not a backup.

## Restoring

Restore into a database with a new name first, and look at it:

    python scripts/database_backup.py restore backups/clip-20261017T020000Z.dump --into clip_restore

The script refuses the live database's name unless `--replace-live` is given. To bring
back the live database, stop the application, restore with `--replace-live`, and start
it again. The restore test (`tests/test_backup_restore.py`) restores a real dump into a
scratch database and checks the migration version, so a restore that no longer works
fails CI.

## What a restore undoes

- **Erasures after the backup.** Restoring puts back what was in the backup, including a
  student erased since. Their deletion request and the audit entries written since are
  lost with the rest. After a restore, run the erasures again from the team's records.
- **Purged sessions.** The next scheduled purge deletes sessions older than
  `DATA_RETENTION_DAYS` again.

## How long backups are kept

Deleted data persists in backups, so keep as few as recovery needs. The default is
30 daily backups, so erased and purged data leaves them within a month, well inside the
120-day retention period. Do not raise `--keep` past what the retention promise allows.

## Operations (demo deployment)

Owner: BBIS (Nour), backup operator Shezin. Proposed targets: lose at most one day of data (RPO 24 h) and recover within an hour (RTO 1 h).

- **Nightly:** `deploy/nightly_backup.sh` runs `deploy/backup.sh`, encrypts the new database and uploads files, checks each encrypted copy decrypts to the original, and only then deletes the plaintext. If encryption or the check fails it exits non-zero and keeps the plaintext, so the only backup is never lost. Backups older than 30 days are deleted.
- **Key:** generated with `openssl rand -base64 32`, stored in `~/.clip-backup-key` with mode 600 (override with `CLIP_BACKUP_KEY`), never committed. Both operators hold a copy in a password manager. Without it the backups cannot be restored.
- **Off-site:** upload only the `.enc` files to the operators' storage.
- **Alert:** `deploy/check_backup_age.sh` exits 1 when no non-empty `clip-*.sql.gz.enc` is newer than 26 hours. The alert goes to stderr; set `ALERT_WEBHOOK_URL` (for example a Teams incoming webhook) to also POST it. On macOS it also shows a notification.
- **Cron:** stdout goes to the log and stderr is mailed to `MAILTO`, so any failure of either job reaches the operator. On a server, set `MAILTO` to the operator's address and make sure the host can send mail.

      MAILTO=operator@example.com
      0 2 * * * /path/to/repo/deploy/nightly_backup.sh >> /var/log/clip-backup.log
      0 8 * * * /path/to/repo/deploy/check_backup_age.sh >> /var/log/clip-backup.log

### Restoring an encrypted backup

`deploy/restore.sh` takes the plain files, so decrypt them into a private folder first and delete them afterwards:

    umask 077 && mkdir -p /tmp/clip-restore
    K=$HOME/.clip-backup-key
    openssl enc -d -aes-256-cbc -pbkdf2 -pass file:$K -in backups/clip-<time>.sql.gz.enc -out /tmp/clip-restore/clip-<time>.sql.gz
    openssl enc -d -aes-256-cbc -pbkdf2 -pass file:$K -in backups/clip-<time>-uploads.tar.gz.enc -out /tmp/clip-restore/clip-<time>-uploads.tar.gz
    sh deploy/restore.sh /tmp/clip-restore/clip-<time>.sql.gz /tmp/clip-restore/clip-<time>-uploads.tar.gz
    rm -rf /tmp/clip-restore

If the database step fails it is rolled back and the backend restarts on the old data. If the uploads step fails after the database was restored, the backend is left stopped with a warning, so it never runs with files that do not match the database. Fix the archive and run the restore again.

### Replaying erasures after a restore

A restore brings back every student erased after the backup, and their deletion request and audit entries with it. So:

1. When an erasure is executed, the operator adds a line to an erasure log kept with the off-site backups, not in the database: date, deletion request ID and student ID.
2. After any restore, look up the backup's timestamp. Every erasure in the log dated after it must be run again: file a new deletion request for that student, have a second administrator approve it, and execute it.
3. Record the replay in the log. Never test this against the live database.