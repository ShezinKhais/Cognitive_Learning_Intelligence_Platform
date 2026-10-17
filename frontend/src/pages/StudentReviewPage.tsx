import { useId, useState } from 'react'
import { ChevronDown, FileText } from 'lucide-react'
import { Link, useParams } from 'react-router'

import { buttonStyles } from '../components/ui/button'
import { cn } from '../components/ui/cn'
import { EmptyState, MetaLine, PageBody, PageHeader, Panel, SkeletonRows, Tag } from '../components/ui/primitives'
import SegmentedTabs from '../components/ui/SegmentedTabs'
import { formatRelative, sinceVerb } from '../features/format/relativeTime'
import { comprehensionText, comprehensionTone, needsReview, reviewError } from '../features/review/reviewDisplay'
import type { ReviewAnswer, ReviewPage, ReviewSession, ReviewSources, StudentReview } from '../features/review/reviewTypes'
import { useReviewResource } from '../features/review/useReviewResource'

const PAGE_SIZE = 20

/** Every finished session a student can look back on. Works when live
 * sessions are switched off, since it does not need the session list. */
export function StudentReviewHistoryPage() {
  const [offset, setOffset] = useState(0)
  const { data, error, status, retry } = useReviewResource<ReviewPage<ReviewSession>>(
    `/student-reviews?limit=${PAGE_SIZE}&offset=${offset}`,
  )

  return (
    <>
      <PageHeader
        title="Past sessions"
        description="Go back over your own answers, with the slides each question came from."
      />
      <PageBody>
        {error ? (
          // The list has no one session to be missing, so a 404 here means
          // the route itself is not on this server.
          <LoadError message={status === 404 ? reviewError(501) : error} retry={retry} />
        ) : !data ? (
          <SkeletonRows label="Loading your past sessions" />
        ) : data.items.length === 0 ? (
          <EmptyState art="lecture" title="Nothing to look back on yet">
            A session appears here once it has ended.
          </EmptyState>
        ) : (
          <>
            <ul className="divide-y divide-border rounded-lg border border-border bg-card">
              {data.items.map((session) => (
                <li key={session.id}>
                  <Link
                    to={`/student/reviews/${session.id}`}
                    className="group flex items-center justify-between gap-4 px-5 py-4 transition-colors hover:bg-muted/50"
                  >
                    <span className="min-w-0">
                      <span className="block truncate font-semibold group-hover:text-primary">{session.title}</span>
                      <MetaLine
                        className="mt-0.5"
                        items={[session.course_code, session.ended_at ? sinceVerb('Ended', session.ended_at) : 'Ended']}
                      />
                    </span>
                    <span className="shrink-0 text-sm font-semibold text-primary">Review</span>
                  </Link>
                </li>
              ))}
            </ul>
            <Pager offset={offset} total={data.total} onChange={setOffset} noun="sessions" />
          </>
        )}
      </PageBody>
    </>
  )
}

export default function StudentReviewPage() {
  const { sessionId } = useParams<{ sessionId: string }>()
  if (!sessionId) {
    return (
      <PageBody>
        <EmptyState title="This review could not be found" />
      </PageBody>
    )
  }
  return <Review key={sessionId} sessionId={sessionId} />
}

type AnswerFilter = 'all' | 'revisit'

function Review({ sessionId }: { sessionId: string }) {
  const [offset, setOffset] = useState(0)
  const [filter, setFilter] = useState<AnswerFilter>('all')
  const { data, error, retry } = useReviewResource<StudentReview>(
    `/student-reviews/${encodeURIComponent(sessionId)}?limit=${PAGE_SIZE}&offset=${offset}`,
  )
  const back = { to: '/student/reviews', label: 'Past sessions' }

  if (error) {
    return (
      <>
        <PageHeader title="Session review" back={back} />
        <PageBody>
          <LoadError message={error} retry={retry} />
        </PageBody>
      </>
    )
  }
  if (!data) {
    return (
      <>
        <PageHeader title="Session review" back={back} />
        <PageBody>
          <SkeletonRows label="Loading your answers" />
        </PageBody>
      </>
    )
  }

  const toRevisit = data.answers.filter(needsReview)
  const shown = filter === 'revisit' ? toRevisit : data.answers

  return (
    <>
      <PageHeader
        title={data.session.title}
        tabTitle={`Review, ${data.session.title}`}
        back={back}
        description={
          <>
            {data.session.course_code}
            {data.session.ended_at && `, ${sinceVerb('ended', data.session.ended_at)}`}. Only your own answers,
            never a ranking against the class.
          </>
        }
        actions={
          <Link to={`/student/session/${sessionId}/summary`} className={buttonStyles({ intent: 'secondary' })}>
            Topic summary
          </Link>
        }
      />
      <PageBody>
        <div className="grid gap-6 md:grid-cols-2">
          <Panel title="Your answers" description="Unanswered questions are not counted as wrong.">
            <p className="text-lg">
              <strong>{data.questions_attempted}</strong> answered
              {data.questions_missed > 0 && (
                <>
                  , <strong>{data.questions_missed}</strong> not answered
                </>
              )}
            </p>
          </Panel>
          <Panel title="Engagement" description="Kept apart from how well you understood.">
            <p className="font-semibold">Not recorded for this session</p>
            <p className="mt-1 text-sm text-muted-foreground">{data.engagement.explanation}</p>
          </Panel>
        </div>

        <section aria-labelledby="answers-heading" className="mt-10">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <h2 id="answers-heading" className="text-lg font-bold">
              Answer by answer
            </h2>
            {data.answers.length > 0 && (
              <SegmentedTabs
                label="Show answers"
                dense
                value={filter}
                onChange={setFilter}
                segments={[
                  { key: 'all', label: `All ${data.answers.length}` },
                  { key: 'revisit', label: `To revisit ${toRevisit.length}` },
                ]}
              />
            )}
          </div>

          {data.answers.length === 0 ? (
            <EmptyState title="No answers from you in this session">
              With nothing answered, there is nothing to say about what you understood.
            </EmptyState>
          ) : shown.length === 0 ? (
            <EmptyState title="Nothing to revisit on this page">
              Every marked answer here was right. Answers without a mark are under All.
            </EmptyState>
          ) : (
            <ol className="space-y-3">
              {shown.map((answer) => (
                <li key={answer.id}>
                  <Answer answer={answer} sessionId={sessionId} />
                </li>
              ))}
            </ol>
          )}
          <Pager offset={offset} total={data.total} onChange={setOffset} noun="answers" />
        </section>
      </PageBody>
    </>
  )
}

function Answer({ answer, sessionId }: { answer: ReviewAnswer; sessionId: string }) {
  const [open, setOpen] = useState(false)
  const sourcesId = useId()
  const revisit = needsReview(answer)
  const uncertain = answer.confidence !== null && answer.confidence < 0.6

  return (
    <article className="rounded-lg border border-border bg-card px-5 py-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <MetaLine items={[answer.topic ?? 'No topic', formatRelative(answer.submitted_at)]} />
        <Tag tone={comprehensionTone(answer)}>{comprehensionText(answer)}</Tag>
      </div>
      <h3 className="mt-2 whitespace-pre-wrap font-semibold">{answer.question}</h3>
      <p className="mt-3 text-sm font-semibold text-muted-foreground">Your answer</p>
      <p className="mt-0.5 whitespace-pre-wrap break-words">{answer.answer}</p>
      {answer.label && answer.confidence !== null && !uncertain && (
        <p className="mt-2 text-sm text-muted-foreground">
          {Math.round(answer.confidence * 100)}% sure of this reading. It is an estimate, not a grade.
        </p>
      )}
      {revisit && (
        <p className="mt-2 text-sm">Read the slide again, put the idea in your own words, and ask your lecturer about anything still unclear.</p>
      )}
      <button
        type="button"
        aria-expanded={open}
        aria-controls={sourcesId}
        onClick={() => setOpen((value) => !value)}
        className={cn(buttonStyles({ intent: revisit ? 'secondary' : 'quiet' }), 'mt-3', !revisit && '-ml-3')}
      >
        <FileText size={15} aria-hidden />
        {open ? 'Hide the source' : 'Show where this came from'}
        <ChevronDown size={15} aria-hidden className={cn('transition-transform', open && 'rotate-180')} />
      </button>
      {open && (
        <div id={sourcesId} className="mt-3">
          <Sources sessionId={sessionId} responseId={answer.id} />
        </div>
      )}
    </article>
  )
}

function Sources({ sessionId, responseId }: { sessionId: string; responseId: string }) {
  const { data, error, retry } = useReviewResource<ReviewSources>(
    `/student-reviews/${encodeURIComponent(sessionId)}/responses/${encodeURIComponent(responseId)}/sources`,
  )
  if (error) return <LoadError message={error} retry={retry} />
  if (!data) return <p role="status" className="text-sm text-muted-foreground">Finding the source…</p>
  if (data.items.length === 0) {
    return (
      <p role="status" className="text-sm text-muted-foreground">
        The source is no longer kept. Ask your lecturer for the slides; nothing is made up to fill the gap.
      </p>
    )
  }
  return (
    <section aria-label="Where this question came from" className="space-y-2">
      {data.items.map((source) => (
        <blockquote key={source.chunk_id} className="rounded-md border-l-2 border-primary bg-muted/40 px-4 py-3">
          <MetaLine
            items={[
              <span key="title" className="font-semibold text-foreground">{source.material_title}</span>,
              source.source_page !== null ? `Page or slide ${source.source_page}` : null,
              source.match === 'excerpt' ? 'The passage the question came from' : 'Same page, passage not confirmed',
            ]}
          />
          <p className="mt-2 whitespace-pre-wrap break-words text-sm">{source.text}</p>
        </blockquote>
      ))}
      {data.has_more && (
        <p className="text-sm text-muted-foreground">These are the first five matches. Your lecturer has the whole page.</p>
      )}
    </section>
  )
}

function LoadError({ message, retry }: { message: string; retry: () => void }) {
  return (
    <div role="alert">
      <EmptyState
        title="This could not be loaded"
        action={
          <button type="button" onClick={retry} className={buttonStyles({ intent: 'secondary' })}>
            Try again
          </button>
        }
      >
        {message}
      </EmptyState>
    </div>
  )
}

function Pager({
  offset,
  total,
  noun,
  onChange,
}: {
  offset: number
  total: number
  noun: string
  onChange: (offset: number) => void
}) {
  if (total <= PAGE_SIZE) return null
  return (
    <nav aria-label={`More ${noun}`} className="mt-5 flex flex-wrap items-center justify-between gap-3">
      <span className="text-sm text-muted-foreground tabular-nums">
        {offset + 1} to {Math.min(offset + PAGE_SIZE, total)} of {total} {noun}
      </span>
      <span className="flex gap-2">
        <button
          type="button"
          className={buttonStyles({ intent: 'secondary' })}
          disabled={offset === 0}
          onClick={() => onChange(Math.max(0, offset - PAGE_SIZE))}
        >
          Previous
        </button>
        <button
          type="button"
          className={buttonStyles({ intent: 'secondary' })}
          disabled={offset + PAGE_SIZE >= total}
          onClick={() => onChange(offset + PAGE_SIZE)}
        >
          Next
        </button>
      </span>
    </nav>
  )
}
