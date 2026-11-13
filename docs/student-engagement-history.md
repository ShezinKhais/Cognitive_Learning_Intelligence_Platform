# Student engagement history: the contract (#243)

What a student may see about their own engagement across finished classes, and
what they are never shown. Proposed for the team to confirm; the code follows it.

## What a student sees

`GET /api/v1/me/engagement-history` (students only, their own record, newest
first, paginated). Each finished class of a course they are on has:

| Fact | Source | When it is missing |
|---|---|---|
| Joined | `session_participant` | `false`, which is a fact, not an estimate |
| Checkpoints sent | `delivered_question` | `0` means none were sent |
| Answered | `student_response` | `0` |
| Missed | `missed_response`: sent while connected, closed unanswered | `0` |
| Camera minutes | `attention_signal_summary` windows with a face or gaze reading | `not_consented` or `none_recorded`, never `0` |
| Microphone minutes | the same windows with a speaking reading | `not_consented` or `none_recorded`, never `0` |

The Progress page shows this as "Class by class". The per-class review (#278)
shows the same reading availability for one class.

## What a student never sees here

- **No engagement score.** The stored summaries carry no validated confidence
  for one, so none is invented. A future score needs its own agreement and
  calibration evidence.
- **No mixing with comprehension.** How well they understood stays in the
  review and topic summaries. Nothing here says anything about understanding.
- **No zero for a missing reading.** A camera that was off, not agreed to, or
  purged is reported by name, and the page says so in words.
- **Nothing about another student,** and nothing from a class that is still
  running or was cancelled.

## Consent

Readings follow consent as it stands now:

- Engagement monitoring withdrawn: no camera or microphone figures at all, for
  any class.
- A sensor counts only windows from the later of its own grant and the
  monitoring grant. A window recorded before a withdrawal and a later regrant
  does not come back.
- Participation (joined, answered, missed) is part of taking the class and is
  shown regardless, as it is in the review.

## Retention and erasure

Attention windows removed by the retention purge, or by an approved erasure,
are not there to count, so the class shows `none_recorded`. The participation
facts follow the same retention as the rest of the class record.

## Tests

`backend/tests/test_student_engagement.py`: consented and unconsented sensors,
windows before the grant, another student's windows in the same class,
withdrawn monitoring, a class with no readings, and a class not yet ended.

## Not decided here

A trend over time or a comparison with the class average. Both risk reading
as a mark, and need agreement with Cyber 1 (scoring) and the lecturer-facing
engagement history (#232) first.
