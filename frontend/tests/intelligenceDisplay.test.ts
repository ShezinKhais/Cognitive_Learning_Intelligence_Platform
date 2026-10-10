import assert from 'node:assert/strict'
import test from 'node:test'

import {
  classificationLabel,
  confidenceLabel,
  explanationText,
  recommendationText,
} from '../src/features/intelligence/intelligenceDisplay.ts'

test(
  'classification labels use the Design Document terminology',
  () => {
    assert.equal(
      classificationLabel(
        'mastered',
      ),
      'Mastered',
    )

    assert.equal(
      classificationLabel(
        'partial',
      ),
      'Partial',
    )

    assert.equal(
      classificationLabel(
        'struggling',
      ),
      'Struggling',
    )
  },
)

test(
  'missing classification has a safe unavailable label',
  () => {
    assert.equal(
      classificationLabel(null),
      'Classification unavailable',
    )

    assert.equal(
      classificationLabel(
        undefined,
      ),
      'Classification unavailable',
    )
  },
)

test(
  'confidence converts an authoritative zero-to-one score into a percentage',
  () => {
    assert.equal(
      confidenceLabel(0),
      '0% confidence',
    )

    assert.equal(
      confidenceLabel(0.874),
      '87% confidence',
    )

    assert.equal(
      confidenceLabel(1),
      '100% confidence',
    )
  },
)

test(
  'missing or invalid confidence is not fabricated',
  () => {
    assert.equal(
      confidenceLabel(null),
      'Confidence unavailable',
    )

    assert.equal(
      confidenceLabel(
        undefined,
      ),
      'Confidence unavailable',
    )

    assert.equal(
      confidenceLabel(
        Number.NaN,
      ),
      'Confidence unavailable',
    )

    assert.equal(
      confidenceLabel(-0.1),
      'Confidence unavailable',
    )

    assert.equal(
      confidenceLabel(1.1),
      'Confidence unavailable',
    )
  },
)

test(
  'authoritative explanation text is preserved',
  () => {
    assert.equal(
      explanationText(
        'Most responses showed partial understanding.',
      ),
      'Most responses showed partial understanding.',
    )
  },
)

test(
  'missing explanation is not fabricated',
  () => {
    assert.equal(
      explanationText(null),
      'Explanation unavailable',
    )

    assert.equal(
      explanationText(
        undefined,
      ),
      'Explanation unavailable',
    )

    assert.equal(
      explanationText('   '),
      'Explanation unavailable',
    )
  },
)
test(
  'authoritative recommendation text is preserved',
  () => {
    assert.equal(
      recommendationText(
        'Review the topic before continuing.',
      ),
      'Review the topic before continuing.',
    )
  },
)

test(
  'missing recommendation is not fabricated',
  () => {
    assert.equal(
      recommendationText(null),
      'Recommendation unavailable',
    )

    assert.equal(
      recommendationText(
        undefined,
      ),
      'Recommendation unavailable',
    )

    assert.equal(
      recommendationText('   '),
      'Recommendation unavailable',
    )
  },
)