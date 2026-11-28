# Real Teams acceptance — #234 / #239

Tracks #234 (G01, G31) and #239 (G08). Linked from #175.
Procedure: [teams-release-acceptance.md](../teams-release-acceptance.md)

## Build and environment
- Tested on: [date] by [names]
- Release SHA: [sha]
- Images: backend [id] / web [id]
- Teams package: v[x.y.z], ZIP sha256 [hash], schema 1.17 validation [passed/failed]
- Frontend lockfile sha256: [hash]
- Speech model: faster-whisper-base.en, sha [hash], language en
- Clients: Teams desktop [version] on macOS; Teams web on [browser + version]
- Tenant: approved test tenant; synthetic, consented teaching phrases only

## Results

| ID | Client | Expected | Actual | Status | Evidence / defect |
|---|---|---|---|---|---|
| TEAM-01 | | Install validated ZIP, lecturer + student SSO, link fresh meeting, start class | | Not run | |
| TEAM-02 | | Checkpoint, targeted pop-up, answer/feedback, @CLIP help/status, reconnect, breakout panel | | Not run | |
| TEAM-03 | | Student review opens in Teams client and web browser | | Not run | |
| SPEECH-01 | | Unreviewed timestamped note appears; student catch-up cites it | | Not run | |
| SPEECH-02 | | Delay, omissions, wrong terms recorded under jargon/noise/varied delivery | | Not run | |
| SPEECH-03 | | Stop/hide/mic loss/pause/end each stop capture; no auto restart | | Not run | |
| GRAPH-01 | | Draft private until published; publish/edit/remove reflected for student | | Not run | |
| GRAPH-02 | | Manual import imports text only; no recording/audio stored | | Not run | |

## Supported / unsupported meeting and client types
- Scheduled private meeting: [result]
- Channel meeting: not advertised by current groupChat-only manifest

## Defects raised
- [none yet]

## Limitations observed
- [fill after testing]