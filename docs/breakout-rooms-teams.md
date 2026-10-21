# Breakout rooms in Microsoft Teams: what C.L.I.P can and cannot do

Owner: General CS, Phase 8. Related: [signals-and-rooms.md](signals-and-rooms.md).

This note records what Teams lets an app do with breakout rooms, the design
C.L.I.P uses because of it, and what still has to be checked in a real tenant.

## What Teams offers an app

Checked against Microsoft's Teams developer documentation on 21 October 2026:
[apps in meetings](https://learn.microsoft.com/en-us/microsoftteams/platform/apps-in-teams-meetings/teams-apps-in-meetings),
[meeting app APIs](https://learn.microsoft.com/en-us/microsoftteams/platform/apps-in-teams-meetings/meeting-apps-apis) and
[tabs for meetings](https://learn.microsoft.com/en-us/microsoftteams/platform/apps-in-teams-meetings/build-tabs-for-meeting).

| Need | Available to an app? |
|---|---|
| Create breakout rooms, or assign students to them | No. The meeting app APIs do not cover it, and no Microsoft Graph endpoint for it was found. Rooms are created and managed by the organiser, or a presenter made a room manager, in the Teams desktop client. |
| Read which room a participant is in | No. "Get participant" returns the role, whether they are in the meeting, and the meeting chat id, with no room. |
| Events when rooms open or close | No. A bot receives `meetingStart`, `meetingEnd`, `meetingParticipantJoin` and `meetingParticipantLeave`, and participant events only for scheduled meetings. |
| Run the side panel in a meeting | Yes, in the Teams desktop client. The web client needs developer preview. The documentation does not say whether the panel follows a student into a breakout room. |

The Azure Communication Services calling SDK can join a user to the room they
were assigned, but it cannot manage rooms either, and C.L.I.P does not use it.

## The design that follows

C.L.I.P never creates or reads rooms through Teams. It asks the student.

1. The lecturer opens breakout rooms in Teams as usual.
2. In the C.L.I.P side panel, the student picks the room they are in
   (`BreakoutRoomSelection`). This sends `room.confirm` with the room's label.
3. Each room's status comes from its members' own voice-activity flags, worked
   out on their devices. No audio leaves a device.
4. The lecturer's live page shows every room (`RoomsPanel`) as Talking, Quiet,
   Needs you, or No readings yet. A room silent for too long raises one
   `breakout_inactive` alert.

A room nobody has reported from is `unknown`, never `quiet`, so a missing
confirmation is not read as a silent group. Students are never sent another
room's status.

This works the same with or without a tenant, which is why it can be shown in
the demo through the simulated meeting panel.

## Still to check in a real tenant

| Check | Why it matters | If it fails |
|---|---|---|
| The C.L.I.P side panel is available inside a breakout room | The student confirms their room from it | Students confirm the room in the main meeting before moving, or open C.L.I.P in a browser tab |
| What `app.getContext()` returns inside a room: a separate meeting or chat id from the main meeting | If it is separate and stable, the panel could suggest the room instead of asking | Keep asking; nothing depends on it |
| The bot's join and leave events when students move between rooms | Moving into a room may look like leaving the main meeting | Attendance already counts a student as present until their last tab closes |
| Microphone permission inside a room | Voice activity needs it | The room shows `unknown`, and no alert is raised from missing data |

These need the university's Microsoft 365 tenant with custom app upload
allowed. Until then the mock adapter and the simulated panel are the evidence,
and `docs/load-and-recovery.md` covers rooms under load: 40 students in eight
rooms, with the talking rooms active and each silent room raising one alert.
