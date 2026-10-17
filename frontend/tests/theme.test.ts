import assert from 'node:assert/strict'
import test from 'node:test'

import { isThemeChoice, resolveTheme } from '../src/components/shell/theme.ts'

test('matching the device follows its preference', () => {
  assert.equal(resolveTheme('system', true), 'dark')
  assert.equal(resolveTheme('system', false), 'light')
})

test('an explicit choice ignores the device', () => {
  assert.equal(resolveTheme('light', true), 'light')
  assert.equal(resolveTheme('dark', false), 'dark')
})

test('only the three choices are read back from storage', () => {
  assert.equal(isThemeChoice('dark'), true)
  assert.equal(isThemeChoice('contrast'), false)
  assert.equal(isThemeChoice(null), false)
})
