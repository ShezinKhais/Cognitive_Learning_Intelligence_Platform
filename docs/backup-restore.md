# Backups and restore

Owner: BBIS, Phase 7. Code: `backend/scripts/database_backup.py`.

## Taking a backup

From `backend/`, with the usual `.env`:

    python scripts/database_backup.py backup --out backups --keep 30

This dumps the main database, and the history database when `HISTORY_DATABASE_URL` is
set, to `backups/clip-<time>.dump` and `backups/clip_history-<time>.dump`, then keeps the
newest 30 of each. Run it once a day from the host's scheduler (cron or a systemd timer).
It needs the PostgreSQL client tools (`pg_dump`, `pg_restore`, `createdb`), best of\nthe same major version as the database server. A newer client works: its extra\n`transaction_timeout` setting is the one restore error the script accepts.

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
