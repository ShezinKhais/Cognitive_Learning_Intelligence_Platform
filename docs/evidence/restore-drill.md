## Backup restoration

Backed up a seeded term (22,084 rows in 34 main and 2 history tables), deleted every session and student from the live copy, then restored both databases into new ones.

| Step | Seconds |
|---|---|
| backup main | 0.2 |
| backup history | 0.1 |
| restore main | 0.5 |
| restore history | 0.1 |

| Check | Result | Detail |
|---|---|---|
| Backup files are private (mode 600) | PASS | 833 KB in all |
| The disaster really removed data from the live copy | PASS | students 30 -> 0, sessions 45 -> 0 |
| Every table in the restored main database has its original row count | PASS | 34 tables, 21,994 rows |
| Every table in the restored history database has its original row count | PASS | 2 tables, 90 rows |
| The restored main database passes the integrity checks | PASS | 6 of 6 checks |
