## Deletion test

One student was erased end to end on a throwaway database with a separate history database, using the same services the admin routes call.

| Check | Result | Detail |
|---|---|---|
| The student's export matched their stored data | PASS | 204 answers, 1 history rows |
| The requester cannot approve their own request | PASS |  |
| Nothing runs before approval, and nothing was deleted by trying | PASS |  |
| The student is gone from the main database | PASS | removed {'answers': 204, 'engagement': 102, 'attention': 170, 'attendance': 34, 'labels': 204} |
| The outcome counts what was removed | PASS | {'answers': 204, 'attention_summaries': 170, 'prompts': 0, 'engagement': 102, 'teams_records': 0, 'alerts': 0, 'recommendations': 0, 'history_rows': 1} |
| Their history rows are gone | PASS | 1 -> 0 |
| Nobody else's data changed | PASS | every other student's rows are intact |
| The account is anonymised, not deleted | PASS | Deleted student |
| The request and its audit trail remain | PASS | STUDENT_DATA_EXPORTED, DELETION_REQUESTED, DELETION_APPROVED, DELETION_EXECUTED |
| The student's export now says not found | PASS |  |
| Executing the same request again is refused | PASS |  |
| With history down, execution stops before touching anything | PASS | student and history rows intact |
| The retry finishes the job | PASS | history 1 -> 0 |
| A failure after the history commit leaves the student and request intact | PASS | history 1 -> 0, request approved |
| Running it again finishes the erasure | PASS | request executed |
| An erasure racing a purge leaves no history behind | PASS | purge waited for the erasure; history 1 -> 0 |
