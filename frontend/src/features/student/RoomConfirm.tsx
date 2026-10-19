import { BreakoutRoomSelection } from './BreakoutRoomSelection'
import type { LiveErrorEvent } from './liveSessionTypes'

/** Report a student-selected room, not a confirmed Teams assignment. */
export default function RoomConfirm({ onConfirm, enabled, serverError }: {
  onConfirm: (label: string) => boolean
  enabled: boolean
  serverError: LiveErrorEvent | null
}) {
  return <BreakoutRoomSelection enabled={enabled} onSelect={onConfirm} serverError={serverError} />
}
