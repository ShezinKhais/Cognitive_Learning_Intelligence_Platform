import { useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { Link } from 'react-router'

import { apiAuthenticatedRequest } from '../api'
import { buttonStyles } from '../components/ui/button'
import { EmptyState, PageBody, PageHeader, Panel, SkeletonRows, Tag, type Tone } from '../components/ui/primitives'
import SegmentedTabs from '../components/ui/SegmentedTabs'
import { revisitFirst, topicProgress, type Mastery, type TopicProgress } from '../features/review/progress'
import type { ReviewPage, ReviewSession, StudentReview } from '../features/review/reviewTypes'

const WORD: Record<Mastery, string> = { mastered: 'Mastered', partial: 'Partly there', struggling: 'Revisit this' }
const TONE: Record<Mastery, Tone> = { mastered: 'good', partial: 'mixed', struggling: 'poor' }
const FILL: Record<Mastery, string> = { mastered: 'bg-success', partial: 'bg-warning', struggling: 'bg-critical' }
const ADVICE: Record<Mastery, string> = {
  mastered: 'You have this. A quick look before the exam is enough.',
  partial: 'You are close. Reread those slides and try the tutor on one question.',
  struggling: 'Start here. Reread those slides, then ask the tutor to walk you through it.',
}

type Order = 'revisit' | 'name'

/** Everything the student has finished, each with its answers. The list
 * route carries no answers, so each session is read once. */
async function loadReviews(): Promise<StudentReview[]> {
  const list = await apiAuthenticatedRequest<ReviewPage<ReviewSession>>('/student-reviews?limit=50&offset=0')
  return Promise.all(
    list.items.map((session) =>
      apiAuthenticatedRequest<StudentReview>(`/student-reviews/${encodeURIComponent(session.id)}?limit=100&offset=0`),
    ),
  )
}

/** A student's topics across every finished session, from their own answers. */
export default function StudentProgressPage() {
  const [reviews, setReviews] = useState<StudentReview[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [order, setOrder] = useState<Order>('revisit')
  const [open, setOpen] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    loadReviews().then(
      (loaded) => !cancelled && setReviews(loaded),
      () => !cancelled && setError('Your sessions could not be loaded. Check your connection and try again.'),
    )
    return () => {
      cancelled = true
    }
  }, [])

  const topics = reviews ? topicProgress(reviews) : []
  const shown = order === 'revisit' ? revisitFirst(topics) : [...topics].sort((a, b) => a.topic.localeCompare(b.topic))
  const toRevisit = topics.filter((topic) => topic.latest !== 'mastered').length

  return (
    <>
      <PageHeader
        title="Progress over time"
        description="Your topics across every session you have finished, so you know what to revisit before an exam."
      />
      <PageBody>
        {error ? (
          <EmptyState title="This could not be loaded">{error}</EmptyState>
        ) : !reviews ? (
          <SkeletonRows label="Loading your topics" />
        ) : topics.length === 0 ? (
          <EmptyState art="lecture" title="Nothing to chart yet">
            Topics appear here once a session you answered in has ended and your answers are marked.
          </EmptyState>
        ) : (
          <Panel
            title={toRevisit === 0 ? 'Every topic is going well' : `${toRevisit} of ${topics.length} topics to revisit`}
            description={`Each mark is one of your ${reviews.length} finished sessions, oldest first. Only your answers count.`}
            actions={
              <SegmentedTabs
                label="Order"
                dense
                value={order}
                onChange={setOrder}
                segments={[
                  { key: 'revisit', label: 'Revisit first' },
                  { key: 'name', label: 'A to Z' },
                ]}
              />
            }
          >
            <motion.ul layout className="-mx-5 -my-4 divide-y divide-border">
              {shown.map((topic) => (
                <TopicRow
                  key={topic.topic}
                  topic={topic}
                  expanded={open === topic.topic}
                  onToggle={() => setOpen(open === topic.topic ? null : topic.topic)}
                />
              ))}
            </motion.ul>
          </Panel>
        )}
        {reviews && reviews.length > 0 && (
          <div className="mt-6">
            <Link to="/student/reviews" className={buttonStyles({ intent: 'secondary' })}>
              Go over each session
            </Link>
          </div>
        )}
      </PageBody>
    </>
  )
}

function TopicRow({ topic, expanded, onToggle }: { topic: TopicProgress; expanded: boolean; onToggle: () => void }) {
  const cameUp = topic.marks.filter((mark) => mark.level !== null)
  return (
    <motion.li layout transition={{ type: 'spring', stiffness: 450, damping: 40 }}>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        className="grid w-full grid-cols-[1fr_auto] items-center gap-3 px-5 py-3 text-left transition-colors hover:bg-muted/60 sm:grid-cols-[16rem_1fr_auto]"
      >
        <span className="font-semibold">{topic.topic}</span>
        <span
          className="col-span-2 row-start-2 flex gap-1 sm:col-span-1 sm:row-start-auto"
          aria-label={`Across ${topic.marks.length} sessions`}
        >
          {topic.marks.map((mark) => (
            <span
              key={mark.sessionId}
              title={mark.level ? `${mark.title}: ${WORD[mark.level]}` : `${mark.title}: did not come up`}
              className={`h-4 w-2.5 rounded-sm ${mark.level ? FILL[mark.level] : 'bg-muted'}`}
            />
          ))}
        </span>
        <Tag tone={TONE[topic.latest]}>{WORD[topic.latest]}</Tag>
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
            <div className="px-5 pb-4 text-sm">
              <p className="text-muted-foreground">
                {ADVICE[topic.latest]} From {topic.answered} {topic.answered === 1 ? 'answer' : 'answers'}.
              </p>
              <ul className="mt-2 flex flex-wrap gap-2">
                {cameUp.map((mark) => (
                  <li key={mark.sessionId}>
                    <Link
                      to={`/student/reviews/${mark.sessionId}`}
                      className="inline-flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1 font-semibold hover:bg-muted"
                    >
                      <span aria-hidden className={`h-2 w-2 rounded-full ${FILL[mark.level!]}`} />
                      {mark.title}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.li>
  )
}
