import { useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'

import { Tag, type Tone } from '../../components/ui/primitives'
import DemoFrame from './DemoFrame'
import { SAMPLE_TOPICS, type Mastery } from './sampleData'

const WORD: Record<Mastery, string> = { mastered: 'Mastered', partial: 'Partly there', struggling: 'Revisit this' }
const TONE: Record<Mastery, Tone> = { mastered: 'good', partial: 'mixed', struggling: 'poor' }
const FILL: Record<Mastery, string> = { mastered: 'bg-success', partial: 'bg-warning', struggling: 'bg-critical' }
const RANK: Record<Mastery, number> = { struggling: 0, partial: 1, mastered: 2 }

type Sort = 'revisit' | 'course'

/** The latest word on a topic is what counts: a topic you struggled with in
 * week 3 and mastered in week 8 is mastered. */
function latest(weeks: readonly (Mastery | null)[]): Mastery {
  return [...weeks].reverse().find((week): week is Mastery => week !== null) ?? 'partial'
}

export default function ProgressDemo() {
  const [sort, setSort] = useState<Sort>('revisit')
  const [open, setOpen] = useState<string | null>(null)
  const topics = [...SAMPLE_TOPICS].sort((a, b) =>
    sort === 'revisit' ? RANK[latest(a.weeks)] - RANK[latest(b.weeks)] : 0,
  )

  return (
    <DemoFrame>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-lg font-bold">Your topics in CSIT321</h3>
          <p className="text-sm text-muted-foreground">Each mark is a session where the topic came up.</p>
        </div>
        <div role="tablist" aria-label="Order" className="flex rounded-md border border-border p-0.5 text-sm">
          {(['revisit', 'course'] as const).map((key) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={sort === key}
              onClick={() => setSort(key)}
              className={`rounded px-3 py-1.5 transition-colors ${sort === key ? 'bg-primary font-semibold text-primary-foreground' : 'hover:bg-muted'}`}
            >
              {key === 'revisit' ? 'Revisit first' : 'Course order'}
            </button>
          ))}
        </div>
      </div>

      <motion.ul layout className="mt-4 divide-y divide-border rounded-md border border-border">
        {topics.map((topic) => {
          const now = latest(topic.weeks)
          const expanded = open === topic.topic
          return (
            <motion.li layout key={topic.topic} transition={{ type: 'spring', stiffness: 450, damping: 40 }}>
              <button
                type="button"
                onClick={() => setOpen(expanded ? null : topic.topic)}
                aria-expanded={expanded}
                className="grid w-full grid-cols-[1fr_auto] items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-muted/60 sm:grid-cols-[14rem_1fr_auto]"
              >
                <span className="font-semibold">{topic.topic}</span>
                <span className="col-span-2 row-start-2 flex gap-1 sm:col-span-1 sm:row-start-auto" aria-label={`Across ${topic.weeks.length} weeks`}>
                  {topic.weeks.map((week, index) => (
                    <span
                      key={index}
                      title={week ? `Week ${index + 1}: ${WORD[week]}` : `Week ${index + 1}: did not come up`}
                      className={`h-4 w-2.5 rounded-sm ${week ? FILL[week] : 'bg-muted'}`}
                    />
                  ))}
                </span>
                <Tag tone={TONE[now]}>{WORD[now]}</Tag>
              </button>
              <AnimatePresence initial={false}>
                {expanded && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: 'auto', opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={{ duration: 0.2 }}
                    className="overflow-hidden"
                  >
                    <p className="px-4 pb-3 text-sm text-muted-foreground">
                      From {topic.from}.{' '}
                      {now === 'mastered'
                        ? 'You have this. A quick look before the exam is enough.'
                        : now === 'partial'
                          ? 'You are close. Reread those slides and try the tutor on one question.'
                          : 'Start here. Reread those slides, then ask the tutor to walk you through it.'}
                    </p>
                  </motion.div>
                )}
              </AnimatePresence>
            </motion.li>
          )
        })}
      </motion.ul>
    </DemoFrame>
  )
}
