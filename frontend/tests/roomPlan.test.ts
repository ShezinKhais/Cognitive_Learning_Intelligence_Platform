import assert from 'node:assert/strict'
import test from 'node:test'

import { planBody, roomLabels, splitEvenly } from '../src/features/rooms/roomPlan.ts'

test('rooms are numbered from one', () => {
  assert.deepEqual(roomLabels(3), ['Room 1', 'Room 2', 'Room 3'])
})

test('students are dealt evenly into the rooms', () => {
  const draft = splitEvenly(['a', 'b', 'c', 'd', 'e'], 2, () => 0.5)
  const sizes = Object.values(draft).reduce<Record<string, number>>((count, label) => {
    count[label!] = (count[label!] ?? 0) + 1
    return count
  }, {})
  assert.deepEqual(Object.keys(draft).sort(), ['a', 'b', 'c', 'd', 'e'])
  assert.deepEqual(Object.values(sizes).sort(), [2, 3])
})

test('a room count below one still makes one room', () => {
  assert.deepEqual(new Set(Object.values(splitEvenly(['a', 'b'], 0))), new Set(['Room 1']))
})

test('the body lists only rooms with someone in them, in number order', () => {
  assert.deepEqual(planBody({ a: 'Room 10', b: 'Room 2', c: null, d: 'Room 2' }), {
    rooms: [
      { label: 'Room 2', user_ids: ['b', 'd'] },
      { label: 'Room 10', user_ids: ['a'] },
    ],
  })
})
