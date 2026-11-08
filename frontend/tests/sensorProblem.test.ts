import assert from 'node:assert/strict'
import test from 'node:test'

import { sensorProblem } from '../src/features/attention/sensorProblem.ts'

const named = (name: string) => Object.assign(new Error('x'), { name })

test('a refusal says how to allow the device, in Teams and in a browser', () => {
  assert.match(sensorProblem('Camera', named('NotAllowedError'), true), /App permissions, and turn on Media/)
  assert.match(sensorProblem('Camera', named('NotAllowedError'), false), /address bar/)
})

test('each kind of failure gets its own reason', () => {
  assert.match(sensorProblem('Camera', named('NotReadableError'), false), /in use by another app/)
  assert.match(sensorProblem('Microphone', named('NotFoundError'), false), /No microphone was found/)
  assert.match(sensorProblem('Camera', named('SecurityError'), true), /not allowed to use the camera/)
  assert.match(sensorProblem('Camera', new Error('Insecure'), false), /secure \(https\)/)
  assert.match(sensorProblem('Camera', new Error('Camera processing unavailable'), false), /model could not load/)
  assert.match(sensorProblem('Camera', undefined, false), /Camera unavailable/)
})
