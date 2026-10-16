/**
 * Breakout room activity as the lecturer sees it, from room.status events.
 *
 * The server sends only counts and timings derived from voice activity and
 * answers: never audio, transcripts or who said what. "unknown" is not
 * "quiet": a room with no readings has told us nothing.
 */
export type RoomActivity = 'active' | 'quiet' | 'needs_attention' | 'unknown'

export interface RoomStatus {
  room_label: string
  status: RoomActivity
  members: number
  speaking_now: number
  silence_seconds: number
  task_interactions: number
}

const ACTIVITIES: readonly RoomActivity[] = ['active', 'quiet', 'needs_attention', 'unknown']

function isCount(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0
}

export function isRoomStatus(value: unknown): value is RoomStatus {
  if (typeof value !== 'object' || value === null) return false
  const room = value as Record<string, unknown>
  return (
    typeof room.room_label === 'string' &&
    room.room_label.length > 0 &&
    ACTIVITIES.includes(room.status as RoomActivity) &&
    isCount(room.members) &&
    isCount(room.speaking_now) &&
    isCount(room.silence_seconds) &&
    (room.task_interactions === undefined || isCount(room.task_interactions))
  )
}

/** The rooms after one status update: a room's latest status replaces its
 * last, and a room that empties is dropped. */
export function updateRooms(rooms: readonly RoomStatus[], update: RoomStatus): RoomStatus[] {
  const others = rooms.filter((room) => room.room_label !== update.room_label)
  const next = update.members > 0 ? [...others, { ...update, task_interactions: update.task_interactions ?? 0 }] : others
  return next.sort(byNeed)
}

const NEED: Record<RoomActivity, number> = { needs_attention: 0, quiet: 1, unknown: 2, active: 3 }

/** Rooms that need the lecturer first, then the longest silent. */
function byNeed(a: RoomStatus, b: RoomStatus): number {
  return (
    NEED[a.status] - NEED[b.status] ||
    b.silence_seconds - a.silence_seconds ||
    a.room_label.localeCompare(b.room_label)
  )
}

export function describeSilence(seconds: number): string {
  if (seconds < 60) return seconds <= 5 ? 'Talking now' : `Quiet for ${seconds}s`
  const minutes = Math.floor(seconds / 60)
  return `Quiet for ${minutes} min`
}

export const ACTIVITY_LABEL: Record<RoomActivity, string> = {
  active: 'Talking',
  quiet: 'Quiet',
  needs_attention: 'Needs you',
  unknown: 'No readings yet',
}
