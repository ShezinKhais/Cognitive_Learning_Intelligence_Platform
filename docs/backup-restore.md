# Backups and restore

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

- **Nightly:** `deploy/nightly_backup.sh` runs `deploy/backup.sh`, encrypts the new files to `.enc` with the key in `~/.clip-backup-key`, and deletes backups older than 30 days. Cron: `0 2 * * *`.
- **Key:** generated with `openssl rand -base64 32`, mode 600, never committed. Both operators hold a copy in a password manager. Without it the off-site copies cannot be restored.
- **Off-site:** upload only the `.enc` files to the operators' storage. Decrypt with
  `openssl enc -d -aes-256-cbc -pbkdf2 -pass file:$HOME/.clip-backup-key -in <file>.enc -out <file>`.
- **Alert:** `deploy/check_backup_age.sh` exits 1 and raises a notification when no database backup is newer than 26 hours. Cron: `0 8 * * *`.

### Replaying erasures after a restore

A restore brings back every student erased after the backup, and their deletion request and audit entries with it. So:

1. When an erasure is executed, the operator adds a line to an erasure log kept with the off-site backups, not in the database: date, deletion request ID and student ID.
2. After any restore, look up the backup's timestamp. Every erasure in the log dated after it must be run again: file a new deletion request for that student, have a second administrator approve it, and execute it.
3. Record the replay in the log. Never test this against the live database.
