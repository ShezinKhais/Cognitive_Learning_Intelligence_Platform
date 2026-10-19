## Integrity

| Check | Result | Detail |
|---|---|---|
| One migration head | PASS | a8d2f4c61b73 |
| Database is at the head | PASS | a8d2f4c61b73 |
| Schema matches the models | PASS | no differences |
| Every constraint is validated | PASS | - |
| Every index is valid | PASS | - |
| No foreign key blocks deleting a session or a student | PASS | 21 keys checked |

### Delete rules on keys that point at `session` and `student`

| Table | Column | Points at | On delete |
|---|---|---|---|
| ai_alert | session_id | session | CASCADE |
| ai_recommendation | session_id | session | CASCADE |
| attention_signal_summary | session_id | session | CASCADE |
| breakout_room | session_id | session | CASCADE |
| delivered_question | session_id | session | CASCADE |
| dynamic_prompt | session_id | session | CASCADE |
| engagement_record | session_id | session | CASCADE |
| question | session_id | session | SET NULL |
| session_activity | session_id | session | CASCADE |
| session_participant | session_id | session | CASCADE |
| student_response | session_id | session | CASCADE |
| teams_meeting_link | session_id | session | CASCADE |
| teams_roster_sync | session_id | session | SET NULL |
| ai_alert | student_id | student | SET NULL |
| ai_recommendation | student_id | student | SET NULL |
| attention_signal_summary | student_id | student | CASCADE |
| dynamic_prompt | student_id | student | CASCADE |
| engagement_record | student_id | student | CASCADE |
| missed_response | student_id | student | CASCADE |
| session_participant | student_id | student | CASCADE |
| student_response | student_id | student | CASCADE |
