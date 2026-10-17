## Purge simulation

Seeded 242,137 rows on a throwaway database: 30 students, 300 sessions past retention, 200 current, 5 live-status with old dates. Batch size 25.

Purged 142,050 rows in 0.9 s (155,905 rows/s), 12 session batches, slowest 0.10 s, average 0.08 s.

| Check | Result | Detail |
|---|---|---|
| Preview counts match what was seeded | PASS | 300 sessions, 40500 answers |
| The purge gave way when a class started, then resumed | PASS | first run deleted 75, second finished |
| Every expired session was deleted, once | PASS | 300 of 300 |
| Current and live sessions and everything under them are untouched | PASS | sessions 205, participants 4612, answers 27672, labels 27672, engagement 13836, attention 23060, questions 3030 |
| No active, prepared or ending session was purged | PASS | 5 left |
| Questions stay, with their session link cleared | PASS | 1800 unlinked |
| The audit log adds up to what was deleted | PASS | 300 sessions audited |
| History holds exactly the archived totals | PASS | (6750, 40500, 27000, 20250, 33750), 300 sessions marked |
| A second run deletes nothing and counts nothing twice | PASS | deleted 0 |
