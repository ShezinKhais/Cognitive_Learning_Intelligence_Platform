import assert from 'node:assert/strict'
import test from 'node:test'
import { roomSelection } from '../src/features/student/breakoutRoom.ts'

test('room selection matches the existing label-only contract', () => {
  assert.deepEqual(roomSelection('  Room   2  '), { room_label: 'Room 2' })
  assert.deepEqual(roomSelection('غرفة 2'), { room_label: 'غرفة 2' })
  assert.deepEqual(roomSelection('x'.repeat(100)), { room_label: 'x'.repeat(100) })
})
test('blank, oversized and control-containing room labels are not sent', () => {
  for (const value of ['', '   ', 'x'.repeat(101), 'Room\u0000two', 'Room\n2']) {
    assert.equal(roomSelection(value), null)
  }
})
