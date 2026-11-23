"""A student's own normal, learned from their own session, for fair scoring.

Owner: Cyber 1, Phase 6. Imports nothing from the application.

Engagement scoring compares a student with themselves, never with a fixed
idea of what attention looks like: someone who reads from notes looks away
from the screen all lecture, someone with a poorly placed camera is rarely
"present", and someone who types slowly answers late every time. Held against
a classroom average each of them would be flagged for being themselves.

A baseline is built only from this student's observations in this session,
lives in memory with the session's other engagement evidence, and is dropped
with it (when monitoring consent is withdrawn) or, for the camera parts, when
camera consent is. It is never stored and never compared between students.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median

# Observations needed before a baseline is trusted. Below this the raw reading
# is used and nothing is "relative to normal" yet.
MIN_BASELINE_SAMPLES = 3

# History kept per signal. Bounds memory for a long class and lets the baseline
# follow a student whose situation changes (a laptop moved, a camera fixed).
MAX_BASELINE_SAMPLES = 60

# However little a student looks at the screen, their normal is not treated as
# lower than this, so a few near-zero readings cannot make any later reading
# look "normal for them" at 100%.
GAZE_BASELINE_FLOOR = 0.25

# A camera that finds the student's face less often than this over the session
# is not measuring them reliably (angle, light, a covering). Absence is then
# not evidence, and the signal is set aside rather than scored.
FACE_RELIABLE_RATE = 0.5


@dataclass(slots=True)
class PersonalBaseline:
    gaze: list[float] = field(default_factory=list)
    face: list[bool] = field(default_factory=list)

    def record(self, gaze_ratio: float | None, face_present: bool | None) -> None:
        """Add one client reading. A missing value adds nothing."""
        if gaze_ratio is not None:
            self.gaze.append(gaze_ratio)
            del self.gaze[:-MAX_BASELINE_SAMPLES]
        if face_present is not None:
            self.face.append(face_present)
            del self.face[:-MAX_BASELINE_SAMPLES]

    def purge_visual(self) -> None:
        """Forget everything learned from the camera, as its consent ends."""
        self.gaze.clear()
        self.face.clear()

    def gaze_reference(self) -> float | None:
        """The student's usual share of time looking at the screen, or None
        until there is enough to call it usual."""
        if len(self.gaze) < MIN_BASELINE_SAMPLES:
            return None
        return max(GAZE_BASELINE_FLOOR, median(self.gaze))

    def face_rate(self) -> float | None:
        """How often the camera finds the student's face, or None until
        there is enough to say."""
        if len(self.face) < MIN_BASELINE_SAMPLES:
            return None
        return sum(self.face) / len(self.face)

    def face_reliable(self) -> bool:
        """False when the camera has been missing the student's face so often
        that missing it again says nothing about them."""
        rate = self.face_rate()
        return rate is None or rate >= FACE_RELIABLE_RATE
