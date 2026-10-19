import assert from 'node:assert/strict'
import test from 'node:test'

import { describeSilence, isRoomStatus, updateRooms, type RoomStatus } from '../src/features/live/rooms.ts'

function room(label: string, overrides: Partial<RoomStatus> = {}): RoomStatus {
  return {
    room_label: label,
    status: 'active',
    members: 3,
    speaking_now: 1,
    silence_seconds: 0,
    task_interactions: 0,
    ...overrides,
  }
}

test('only a well formed room status is accepted', () => {
  assert.equal(isRoomStatus(room('A')), true)
  assert.equal(isRoomStatus({ ...room('A'), status: 'loud' }), false)
  assert.equal(isRoomStatus({ ...room('A'), room_label: '' }), false)
  assert.equal(isRoomStatus({ ...room('A'), members: -1 }), false)
  const { task_interactions: _, ...older } = room('A')
  assert.equal(isRoomStatus(older), true)
  assert.equal(isRoomStatus(null), false)
})

test('a room update replaces that room and leaves the others', () => {
  const rooms = updateRooms([room('A'), room('B')], room('A', { speaking_now: 0, silence_seconds: 40, status: 'quiet' }))
  assert.deepEqual(rooms.map((r) => [r.room_label, r.status]), [['A', 'quiet'], ['B', 'active']])
})

test('a room that empties is dropped', () => {
  assert.deepEqual(updateRooms([room('A'), room('B')], room('B', { members: 0 })).map((r) => r.room_label), ['A'])
})

test('rooms that need the lecturer come first, then the longest silent', () => {
  let rooms: RoomStatus[] = []
  rooms = updateRooms(rooms, room('Talking'))
  rooms = updateRooms(rooms, room('Short quiet', { status: 'quiet', silence_seconds: 30 }))
  rooms = updateRooms(rooms, room('Long quiet', { status: 'quiet', silence_seconds: 200 }))
  rooms = updateRooms(rooms, room('Needs you', { status: 'needs_attention', silence_seconds: 10 }))
  assert.deepEqual(rooms.map((r) => r.room_label), ['Needs you', 'Long quiet', 'Short quiet', 'Talking'])
})

test('silence reads in words', () => {
  assert.equal(describeSilence(2), 'Talking now')
  assert.equal(describeSilence(45), 'Quiet for 45s')
  assert.equal(describeSilence(130), 'Quiet for 2 min')
})
