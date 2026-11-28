# Privacy acceptance record ? Issue #169

Status: PARTIALLY VERIFIED
PR: #324

## Automated source review

The source checks below passed on the working branch.
These are source-content checks, not browser acceptance tests.

- [x] Student device indicators explained
- [x] Lecturer transcription explained
- [x] Stored automatic transcripts disclosed
- [x] Private Teams drafts explained
- [x] Consent page links to privacy
- [x] Consent page links to terms
- [x] Teams manifest links to privacy
- [x] Teams manifest links to terms
- [x] README mentions transcription

## Remaining acceptance

- [ ] Obtain team or institution approval of policy wording.
- [ ] Confirm privacy and terms pages load while signed out.
- [ ] Confirm direct reload, keyboard and mobile accessibility.
- [ ] Confirm the packaged Teams manifest resolves correct HTTPS URLs.
- [ ] Open both published policy links inside the real Teams tenant.
- [ ] Check final report and diagrams for consistent privacy statements.
- [ ] Record browser, deployment, tested commit and evidence in #175.

## Important distinctions

Student camera and microphone engagement indicators are
processed locally on the student's device.

Optional lecturer microphone transcription processes temporary
audio chunks on the C.L.I.P server. Recognized text can be
stored and shared with enrolled students.

Teams transcript imports can produce private drafts requiring
lecturer review before publication.

This document does not claim institutional approval or
real Teams acceptance.
