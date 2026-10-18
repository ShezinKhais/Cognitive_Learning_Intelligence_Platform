## Performance queries

Seeded 481,887 rows plus 50,000 audit entries on a throwaway database and ran ANALYZE. Table sizes: attention_signal_summary 113,060, audit_log 50,000, engagement_record 67,836, session_participant 22,612, student_response 135,672.

| Query | Time (ms) | How it reads the data | Verdict |
|---|---|---|---|
| Purge: the next 500 expired sessions | 0.4 | Seq Scan on session (1,005 rows) | OK |
| Purge: archive totals for those sessions | 37.4 | Seq Scan on student_response (135,672 rows); Seq Scan on session (1,005 rows) | WATCH: scans a big table whole |
| Export: a student's answers with labels | 33.2 | Seq Scan on comprehension_result (135,672 rows); Bitmap Index Scan using ix_student_response_student_id | WATCH: scans a big table whole |
| Export: a student's engagement | 1.3 | Bitmap Index Scan using ix_engagement_record_student_id | OK |
| Export: a student's attention summaries | 1.9 | Bitmap Index Scan using ix_attention_signal_summary_student_id | OK |
| Export: a student's prompts | 0.0 | Seq Scan on dynamic_prompt (0 rows) | OK |
| Audit log: newest 50 | 0.0 | Index Scan on audit_log using ix_audit_log_timestamp | OK |
| Audit log: newest 50 of one action | 0.0 | Index Scan on audit_log using ix_audit_log_timestamp | OK |
| Erase one student (cascade, rolled back) | 27.3 | Seq Scan on student (30 rows) | OK |
| Purge one session (cascade, rolled back) | 2.0 | Index Scan on session using session_pkey | OK |

### Cascade triggers that took 1 ms or more

| Query | Constraint | Time (ms) | Calls |
|---|---|---|---|
| Erase one student (cascade, rolled back) | RI_ConstraintTrigger_a_53425 | 19.7 | 4518 |
| Erase one student (cascade, rolled back) | RI_ConstraintTrigger_a_53479 | 3.1 | 1 |
| Erase one student (cascade, rolled back) | RI_ConstraintTrigger_a_53399 | 1.7 | 1 |
| Erase one student (cascade, rolled back) | RI_ConstraintTrigger_a_53489 | 1.2 | 1 |

Big tables read whole by at least one query: comprehension_result, student_response.
