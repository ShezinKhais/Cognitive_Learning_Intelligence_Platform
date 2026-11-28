import assert from 'node:assert/strict'
import test from 'node:test'
import { answerIndices, completeAnswer, type InteractiveCheckpoint } from '../src/features/student/interactiveAnswer.ts'

const ordering: InteractiveCheckpoint = { kind: 'ordering', labels: [], choices: ['Review', 'Read'] }
const matching: InteractiveCheckpoint = { kind: 'matching', labels: ['A', 'B'], choices: ['One', 'Two'] }

test('ordering preserves a full permutation and safely resets malformed drafts', () => {
  assert.deepEqual(completeAnswer(ordering, '[1,0]'), [1, 0])
  for (const draft of ['', 'bad JSON', '[1]', '[1,1]', '[-1,0]', '[0,2]', '["1",0]']) {
    assert.deepEqual(answerIndices(ordering, draft), [0, 1])
  }
})

test('matching keeps partial selections and submits only a complete one-to-one answer', () => {
  assert.deepEqual(answerIndices(matching, ''), [-1, -1])
  assert.deepEqual(answerIndices(matching, '[-1,0]'), [-1, 0])
  assert.deepEqual(completeAnswer(matching, '[1,0]'), [1, 0])
  for (const draft of ['', '[-1,0]', '[0,0]', '[0,2]', '[true,0]']) {
    assert.equal(completeAnswer(matching, draft), null)
  }
})
