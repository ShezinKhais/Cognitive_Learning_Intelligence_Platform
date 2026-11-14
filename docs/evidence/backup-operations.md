## Backup operations — issue #172

First run 11 November 2026, re-tested 14 November 2026 after review, by Nour (BBIS),
branch `Nour-Backup-Operations` (includes Shezin's unmerged `Shezin-Ops-Health` scripts).
Environment: MacBook Air, Docker demo stack (`clip-demo`, `CLIP_ENV=development`),
PostgreSQL 16. Demo accounts and one test upload only; no real student data.

| Check | Result | Detail |
|---|---|---|
| Backup runs while the stack is up | PASS | `deploy/backup.sh`: database 13.5 KB, uploads 427 B |
| Backup files are private | PASS | files `-rw-------`, folder `drwx------` |
| Restore rolls back a change made after the backup | PASS | material renamed after backup; name back to original after restore (11 Nov) |
| Restore time | PASS | 2.8 s total, backend stop to restart (`time`, demo-sized data) |
| Restored database matches the backup | PASS | migration `d8f9a0b1c2d3` and row counts of all 15 non-empty tables identical (`diff` of before/after snapshots) |
| Nightly job encrypts and removes plaintext | PASS | 14 Nov: only `.enc` files left; each copy decrypt-checked against the original before the plaintext is deleted |
| Failed encryption keeps the plaintext | PASS | unreadable key: `FAILED ... (plaintext kept)`, exit 1, plain `.sql.gz` still present |
| Off-machine copy can be restored | PASS | `.enc` downloaded back from Teams decrypts byte-identical to the original (`cmp`) |
| Retention | PASS | nightly script deletes backups older than 30 days, inside the 120-day retention promise |
| Stale/missing/empty backup alert | PASS | `check_backup_age.sh`: fresh `.enc` → OK (exit 0); no backups → ALERT (exit 1); 0-byte `.enc` → ALERT (exit 1) |
| Alert reaches an operator on Linux | CONFIGURED | alert on stderr, mailed by cron `MAILTO`; optional `ALERT_WEBHOOK_URL` POST. Mail delivery not observed |
| Failed uploads restore leaves backend stopped | PASS | corrupt uploads archive: WARNING, exit 2, backend not running |
| Good restore restarts the backend | PASS | `Done.`, exit 0, backend up |
| Scripts run directly | PASS | shebang on line 1, mode 755 |
| Nightly schedule | CONFIGURED | cron 02:00 and 08:00 installed. The 02:00 job produced no backups 12–14 Nov (laptop asleep or Docker stopped) |
| Erasure replay after restore | NOT RUN | dev mode signs in one admin only, and execution needs a second approver. Procedure documented in `docs/backup-restore.md`; erasure itself proven in `deletion-test.md` |

### Limitations
- Off-site copies sit in the CLIP team's General channel, which test accounts can read. Files are encrypted, but a real deployment needs an operators-only folder. Upload is manual.
- The host is a laptop: scheduled jobs run only while it is awake with Docker running, and cron needs Full Disk Access to reach the repo folder. A real deployment needs an always-on host.
- `deploy/backup.sh` does not cover the history database (the demo stack has none); `database_backup.py` does.
- Restore time is for demo-sized data. The BBIS seeded-term drill (`restore-drill.md`, 22,084 rows) restored in under 1 s.
- Operators and RPO/RTO targets are proposed (Nour primary, Shezin backup, RPO 24 h, RTO 1 h) and awaiting team agreement.