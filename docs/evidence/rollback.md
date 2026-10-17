## Migration rollback

Every migration was downgraded one step at a time from the head to the empty database (44 of 44 steps), then upgraded one step at a time back to the head (44 of 44 steps).

**Result: PASS**

| Direction | Migration | Description | Result | Seconds | Note |
|---|---|---|---|---|---|
| down | e7c2a4f95b18 | cascade student data for erasure | PASS | 0.8 |  |
| down | d6b1f3a82e49 | create deletion request table | PASS | 0.7 |  |
| down | c5a9e2f1d874 | cascade session data for retention | PASS | 0.7 |  |
| down | b8e4d1a67c35 | extend audit log for governance | PASS | 0.7 |  |
| down | c5d8e2f71a40 | Keep the bot's meeting reference per meeting, apart from the session link. | PASS | 0.6 |  |
| down | b74d1c93ea20 | Persist authenticated bot conversation references for checkpoint notifications. | PASS | 0.7 |  |
| down | a3f6c8d2e591 | create attention signal summary table | PASS | 0.7 |  |
| down | d5a2f8c61e47 | add explanation columns to ai_alert | PASS | 0.7 |  |
| down | a91c4e7d3b60 | create classifier evaluation tables | PASS | 0.7 |  |
| down | f58a3c9d2e17 | create ai_recommendation table | PASS | 0.7 |  |
| down | e29b6d41f8a3 | create ai_alert table | PASS | 0.7 |  |
| down | c4f81e2a7b95 | add comprehension_result traceability columns | PASS | 0.6 |  |
| down | a7d3e5c91b42 | add question reference_answer and key_points | PASS | 0.7 |  |
| down | 3cc5df760772 | add Teams roster persistence | PASS | 0.7 |  |
| down | 9a52bced38c2 | add Teams user mappings | PASS | 0.7 |  |
| down | e40e0863782e | add Teams meeting persistence | PASS | 0.7 |  |
| down | b3c1e7a9d204 | one comprehension label per response | PASS | 0.7 |  |
| down | 7fb1c9da741b | add live session persistence | PASS | 0.7 |  |
| down | 9b1d3f5a7c20 | add session paused_at | PASS | 0.7 |  |
| down | 4c2e8a91d7b3 | add session lifecycle columns | PASS | 0.7 |  |
| down | 63cc1030dce5 | store upload time with time zone | PASS | 0.7 |  |
| down | f7a642ce1edf | add material warnings | PASS | 0.7 |  |
| down | 5fe8f87afbdb | make question session optional | PASS | 0.7 |  |
| down | b47a09538015 | add material progress percent check | PASS | 0.6 |  |
| down | 2d155233838b | add question review columns | PASS | 0.7 |  |
| down | b5c496365765 | add phase two content pipeline tables | PASS | 0.7 |  |
| down | cd914692a316 | create consent table | PASS | 0.6 |  |
| down | 86dbf6dff19d | add user authentication fields | PASS | 0.7 |  |
| down | c67d0d8ae17d | enforce unique course code | PASS | 0.7 |  |
| down | 62e9a85c991c | fix source material course reference | PASS | 0.7 |  |
| down | 97e029d1159d | fix rag chunk schema | PASS | 0.7 |  |
| down | f16a4d356f03 | create comprehension result table | PASS | 0.7 |  |
| down | 97b8ab121f93 | create student response table | PASS | 0.7 |  |
| down | d1b93a16127a | create breakout room table | PASS | 0.7 |  |
| down | c3314593349e | create dynamic prompt table | PASS | 0.6 |  |
| down | c914a4b3da30 | create engagement record table | PASS | 0.7 |  |
| down | 70bf1eade701 | create question table | PASS | 0.7 |  |
| down | 89980d5732da | create rag chunk table | PASS | 0.7 |  |
| down | 53c88e0048bc | create audit log table | PASS | 0.7 |  |
| down | 8eda16cffa2a | create session table | PASS | 0.7 |  |
| down | ac4cc0d3e078 | create student table | PASS | 0.7 |  |
| down | e81fb9dbc3f0 | create user table | PASS | 0.7 |  |
| down | bfd1d53de1d1 | create course table | PASS | 0.7 |  |
| down | ee527f2fb432 | create source_material table | PASS | 0.7 |  |
| up | ee527f2fb432 | create source_material table | PASS | 0.7 |  |
| up | bfd1d53de1d1 | create course table | PASS | 0.7 |  |
| up | e81fb9dbc3f0 | create user table | PASS | 0.7 |  |
| up | ac4cc0d3e078 | create student table | PASS | 0.7 |  |
| up | 8eda16cffa2a | create session table | PASS | 0.7 |  |
| up | 53c88e0048bc | create audit log table | PASS | 0.7 |  |
| up | 89980d5732da | create rag chunk table | PASS | 0.7 |  |
| up | 70bf1eade701 | create question table | PASS | 0.7 |  |
| up | c914a4b3da30 | create engagement record table | PASS | 0.7 |  |
| up | c3314593349e | create dynamic prompt table | PASS | 0.7 |  |
| up | d1b93a16127a | create breakout room table | PASS | 0.7 |  |
| up | 97b8ab121f93 | create student response table | PASS | 0.7 |  |
| up | f16a4d356f03 | create comprehension result table | PASS | 0.6 |  |
| up | 97e029d1159d | fix rag chunk schema | PASS | 0.7 |  |
| up | 62e9a85c991c | fix source material course reference | PASS | 0.7 |  |
| up | c67d0d8ae17d | enforce unique course code | PASS | 0.7 |  |
| up | 86dbf6dff19d | add user authentication fields | PASS | 0.7 |  |
| up | cd914692a316 | create consent table | PASS | 0.7 |  |
| up | b5c496365765 | add phase two content pipeline tables | PASS | 0.7 |  |
| up | 2d155233838b | add question review columns | PASS | 0.7 |  |
| up | b47a09538015 | add material progress percent check | PASS | 0.6 |  |
| up | 5fe8f87afbdb | make question session optional | PASS | 0.6 |  |
| up | f7a642ce1edf | add material warnings | PASS | 0.7 |  |
| up | 63cc1030dce5 | store upload time with time zone | PASS | 0.7 |  |
| up | 4c2e8a91d7b3 | add session lifecycle columns | PASS | 0.7 |  |
| up | 9b1d3f5a7c20 | add session paused_at | PASS | 0.7 |  |
| up | 7fb1c9da741b | add live session persistence | PASS | 0.7 |  |
| up | b3c1e7a9d204 | one comprehension label per response | PASS | 0.6 |  |
| up | e40e0863782e | add Teams meeting persistence | PASS | 0.7 |  |
| up | 9a52bced38c2 | add Teams user mappings | PASS | 0.7 |  |
| up | 3cc5df760772 | add Teams roster persistence | PASS | 0.7 |  |
| up | a7d3e5c91b42 | add question reference_answer and key_points | PASS | 0.6 |  |
| up | c4f81e2a7b95 | add comprehension_result traceability columns | PASS | 0.7 |  |
| up | e29b6d41f8a3 | create ai_alert table | PASS | 0.7 |  |
| up | f58a3c9d2e17 | create ai_recommendation table | PASS | 0.7 |  |
| up | a91c4e7d3b60 | create classifier evaluation tables | PASS | 0.7 |  |
| up | d5a2f8c61e47 | add explanation columns to ai_alert | PASS | 0.7 |  |
| up | a3f6c8d2e591 | create attention signal summary table | PASS | 0.7 |  |
| up | b74d1c93ea20 | Persist authenticated bot conversation references for checkpoint notifications. | PASS | 0.7 |  |
| up | c5d8e2f71a40 | Keep the bot's meeting reference per meeting, apart from the session link. | PASS | 0.7 |  |
| up | b8e4d1a67c35 | extend audit log for governance | PASS | 0.7 |  |
| up | c5a9e2f1d874 | cascade session data for retention | PASS | 0.7 |  |
| up | d6b1f3a82e49 | create deletion request table | PASS | 0.7 |  |
| up | e7c2a4f95b18 | cascade student data for erasure | PASS | 0.7 |  |

After the full cycle:

## Integrity

| Check | Result | Detail |
|---|---|---|
| One migration head | PASS | e7c2a4f95b18 |
| Database is at the head | PASS | e7c2a4f95b18 |
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
