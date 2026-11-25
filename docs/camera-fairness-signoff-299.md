# Camera fairness sign-off — Issue #299

Status: PENDING HUMAN REVIEW
Related: PR #298 (merged), Issue #160 (device acceptance)

## Scope

This review concerns camera-based indicators. Camera-facing
behaviour is not proof of attention, understanding or participation.

Existing evaluation evidence:
- backend/tests/eval/CV_EVALUATION.md
- backend/tests/eval/cv/RESULTS.md

The current evaluation includes ten participants, but does not
establish fairness across the wider student population.

## Fairness review checklist

| Requirement | Current behaviour | Required review | Status |
|---|---|---|---|
| Calibration | Automatic three-second calibration, with retry | Check students with glasses, disabilities and unusual camera positions | Pending |
| Head-rule fallback | Used until calibration succeeds | Check repeated calibration failure and alternative camera positioning | Pending |
| Combined gaze | Used after successful calibration | Validate glasses, off-centre position, lighting and gaze variation | Pending |
| Default thresholds | Yaw 15 degrees, pitch 30 degrees, roll 30 degrees, iris X 0.3–0.7 | Review unfair false away classifications | Pending |
| Anti-spoofing | Disabled | Review false rejections and spoof detection before enabling | Pending |
| Adaptation | Disabled | Evaluate learning behaviour and unequal effects before enabling | Pending |

## Required acceptance evidence

- [ ] Test with consented participants representing varied camera positions
- [ ] Test with and without glasses
- [ ] Include poor lighting and lower-spec devices
- [ ] Evaluate students unable to hold central gaze
- [ ] Check failed calibration and repeated retries
- [ ] Record false away classifications by condition
- [ ] Complete Teams and device checks under Issue #160
- [ ] Record accessibility and fairness concerns and mitigations
- [ ] Obtain explicit sign-off from the responsible reviewers

## Deployment decision

Do not enable anti-spoofing or adaptation on the basis of the
existing evaluation alone.

Keep camera monitoring disabled in deployment until the required
fairness and device acceptance criteria are satisfied.

## Human sign-off

Reviewer:
Review date:
Decision: Pending
Evidence reviewed:
Conditions or required changes:

No sign-off is claimed by this document.
