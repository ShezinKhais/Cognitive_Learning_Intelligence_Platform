## Backup operations — issue #172

Run 11 November 2026 by Nour (BBIS) on branch `Nour-Backup-Operations` at `3da428f`
(main plus Shezin's unmerged `Shezin-Ops-Health` backup/restore scripts).
Environment: MacBook Air, Docker demo stack (`clip-demo`, `CLIP_ENV=development`),
PostgreSQL 16. Demo accounts and one test upload only; no real student data.

| Check | Result | Detail |
|---|---|---|
| Backup runs while the stack is up | PASS | `deploy/backup.sh`: database 13.5 KB, uploads 427 B |
| Backup files are private | PASS | files `-rw-------`, folder `drwx------` |
| Restore rolls back a change made after the backup | PASS | material renamed after backup; name back to original after restore |
| Restore time | PASS | 2.8 s total, backend stop to restart (`time`, demo-sized data) |
| Restored database matches the backup | PASS | migration `d8f9a0b1c2d3` and row counts of all 15 non-empty tables identical (`diff` of before/after snapshots) |
| Backups are encrypted before leaving the machine | PASS | AES-256-CBC with PBKDF2 (`openssl enc`), key in `~/.clip-backup-key` (mode 600, not in git) |
| Off-machine copy can be restored | PASS | `.enc` downloaded back from Teams decrypts byte-identical to the original (`cmp`) |
| Nightly schedule | CONFIGURED | cron 02:00 runs `deploy/nightly_backup.sh`; manual run passed. Scheduled run not yet observed |
| Retention | PASS | nightly script deletes backups older than 30 days, inside the 120-day retention promise |
| Stale/missing backup alert | PASS | `deploy/check_backup_age.sh`: fresh folder → OK (exit 0); empty folder → ALERT + macOS notification (exit 1). Cron 08:00 |
| Erasure replay after restore | NOT RUN | dev mode signs in one admin only, and execution needs a second approver. Procedure documented in `docs/backup-restore.md`; erasure itself proven in `deletion-test.md` |

### Limitations
- Off-site copies sit in the CLIP team's General channel, which test accounts can read. Files are encrypted, but a real deployment needs an operators-only folder.
- Off-site upload is manual.
- The host is a laptop: the 02:00 job runs only if the Mac is awake and Docker is running, and cron needs Full Disk Access to reach the repo folder.
- Restore time is for demo-sized data. The BBIS seeded-term drill (`restore-drill.md`, 22,084 rows) restored in under 1 s.
- Operators and RPO/RTO targets are proposed (Nour primary, Shezin backup, RPO 24 h, RTO 1 h) and awaiting team agreement.