import assert from 'node:assert/strict'
import test from 'node:test'

import {
  sourceCitationHeading,
  sourceExcerptText,
} from '../src/features/intelligence/citationFormat.ts'

function source(
  overrides: Partial<{
    id: string
    material_title: string
    source_page: number | null
    source_slide: number | null
    excerpt: string | null
  }> = {},
) {
  return {
    id: 'source-1',
    material_title: 'Week 5 Lecture',
    source_page: null,
    source_slide: null,
    excerpt: null,
    ...overrides,
  }
}

test(
  'source citation displays material title and slide',
  () => {
    assert.equal(
      sourceCitationHeading(
        source({
          source_slide: 14,
        }),
      ),
      'Week 5 Lecture · Slide 14',
    )
  },
)

test(
  'source citation displays material title and page',
  () => {
    assert.equal(
      sourceCitationHeading(
        source({
          source_page: 3,
        }),
      ),
      'Week 5 Lecture · Page 3',
    )
  },
)

test(
  'slide is preferred when both slide and page are available',
  () => {
    assert.equal(
      sourceCitationHeading(
        source({
          source_page: 3,
          source_slide: 14,
        }),
      ),
      'Week 5 Lecture · Slide 14',
    )
  },
)

test(
  'source citation can display material title without location',
  () => {
    assert.equal(
      sourceCitationHeading(
        source(),
      ),
      'Week 5 Lecture',
    )
  },
)

test(
  'missing source details are not fabricated',
  () => {
    assert.equal(
      sourceCitationHeading(
        source({
          material_title: '   ',
        }),
      ),
      'Source details unavailable',
    )
  },
)

test(
  'source excerpt preserves authoritative text',
  () => {
    assert.equal(
      sourceExcerptText(
        'A recursive function calls itself.',
      ),
      'A recursive function calls itself.',
    )
  },
)

test(
  'missing source excerpt remains unavailable',
  () => {
    assert.equal(
      sourceExcerptText(null),
      null,
    )

    assert.equal(
      sourceExcerptText(undefined),
      null,
    )

    assert.equal(
      sourceExcerptText('   '),
      null,
    )
  },
)