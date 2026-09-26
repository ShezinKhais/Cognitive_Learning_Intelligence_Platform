"""What each student in a live class has consented to be monitored for.

Owner: Cyber 1, Phase 4.

Consent is granular, and declining one kind never blocks another. For a live
class that means:

- terms: needed to be in the class at all. A socket without it is refused,
  and withdrawing it closes the student's session sockets.
- engagement_monitoring: needed before anything is kept about how engaged a
  student is. Without it the student still sees questions, answers them and
  gets feedback, but no engagement score is computed or reported, their
  attention signals are discarded and no attention prompt is sent to them.
- camera and microphone: needed before the parts of an attention signal
  derived from them are kept. Without them those parts are dropped, and
  engagement scoring renormalises over what is left, so declining never
  lowers a score.

The classroom reads this registry and the socket fills it from the store when
a user is admitted. The consent route applies a withdrawal to it at once, so
collection stops immediately rather than at the next reconnect. A grant is
picked up at the next join instead, once it is surely stored, since the
route's transaction could still roll back.
"""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from app.schemas.events import AttentionSignalPayload
from app.schemas.identity import ConsentType

# Close code for a session socket refused or ended for want of consent. The
# contract's 4003, not a new code, so no client needs to change.
CLOSE_CONSENT = 4003


class ConsentRegistry:
    """The consent each student last held, as far as live classes know.

    A student nobody has told it about holds default, which is nothing in
    production: nobody is monitored on an assumption.
    """

    def __init__(self, default: Iterable[ConsentType] = ()) -> None:
        self._default = frozenset(default)
        self._granted: dict[UUID, frozenset[ConsentType]] = {}
        # Bumped on every decision, so a read that a newer decision overtook
        # cannot overwrite it.
        self._versions: dict[UUID, int] = {}

    def version(self, user_id: UUID) -> int:
        return self._versions.get(user_id, 0)

    def set(self, user_id: UUID, granted: Iterable[ConsentType]) -> frozenset[ConsentType]:
        """Record a decision just made."""
        self._granted[user_id] = frozenset(granted)
        self._versions[user_id] = self.version(user_id) + 1
        return self._granted[user_id]

    def admit(
        self, user_id: UUID, granted: Iterable[ConsentType], read_at: int
    ) -> frozenset[ConsentType]:
        """Record consent read from the store while version was read_at,
        unless a decision has been recorded since. Returns what now holds."""
        if self.version(user_id) != read_at:
            return self.granted(user_id)
        return self.set(user_id, granted)

    def granted(self, user_id: UUID) -> frozenset[ConsentType]:
        return self._granted.get(user_id, self._default)

    def monitored(self, user_id: UUID) -> bool:
        return ConsentType.ENGAGEMENT_MONITORING in self.granted(user_id)


def permitted_signal(
    signal: AttentionSignalPayload, granted: frozenset[ConsentType]
) -> AttentionSignalPayload | None:
    """What of an attention signal may be kept, or None if none of it may."""
    if ConsentType.ENGAGEMENT_MONITORING not in granted:
        return None
    withheld: dict[str, None] = {}
    if ConsentType.CAMERA not in granted:
        withheld |= {"gaze_on_screen_ratio": None, "face_present": None}
    if ConsentType.MICROPHONE not in granted:
        withheld["speaking"] = None
    return signal.model_copy(update=withheld) if withheld else signal
