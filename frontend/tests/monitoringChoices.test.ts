import assert from 'node:assert/strict'
import test from 'node:test'

import { choicesToSave } from '../src/features/student/monitoringChoices.ts'

test('camera and microphone are saved off when monitoring is off', () => {
  assert.deepEqual(choicesToSave({ monitoring: false, camera: true, microphone: true }), {
    monitoring: false,
    camera: false,
    microphone: false,
  })
})

test("with monitoring on, each device is the student's own choice", () => {
  assert.deepEqual(choicesToSave({ monitoring: true, camera: true, microphone: false }), {
    monitoring: true,
    camera: true,
    microphone: false,
  })
  assert.deepEqual(choicesToSave({ monitoring: true, camera: false, microphone: false }), {
    monitoring: true,
    camera: false,
    microphone: false,
  })
})
