import { SocraticChatPanel } from '../features/chat/SocraticChatPanel'
import DiscussionPanel from '../features/discussion/DiscussionPanel'
import { useId, useState } from 'react'
import { ChevronDown, FileText } from 'lucide-react'
import { Link, useParams } from 'react-router'

import { buttonStyles } from '../components/ui/button'
import { cn } from '../components/ui/cn'
import { EmptyState, MetaLine, PageBody, PageHeader, Panel, SkeletonRows, Tag } from '../components/ui/primitives'
import { ProblemState } from '../components/ui/ProblemState'
import { problemArt } from '../components/ui/problem'
import SegmentedTabs from '../components/ui/SegmentedTabs'
import { formatRelative, sinceVerb } from '../features/format/relativeTime'
import { comprehensionText, comprehensionTone, needsReview, reviewError } from '../features/review/reviewDisplay'
import type { MissedQuestion, ReviewAnswer, ReviewPage, ReviewSession, ReviewSources, StudentReview } from '../features/review/reviewTypes'
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
          <LoadError message={status === 404 ? reviewError(501) : error} status={status === 404 ? 501 : status} retry={retry} />
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
  const { data, error, status, retry } = useReviewResource<StudentReview>(
    `/student-reviews/${encodeURIComponent(sessionId)}?limit=${PAGE_SIZE}&offset=${offset}`,
  )
  const back = { to: '/student/reviews', label: 'Past sessions' }

  if (error) {
    return (
      <>
        <PageHeader title="Session review" back={back} />
        <PageBody>
          <LoadError message={error} status={status} retry={retry} />
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
        <DiscussionPanel key={sessionId} sessionId={sessionId!} />
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
            {data.engagement.status === 'readings_available' ? (
              <dl className="grid grid-cols-2 gap-2 text-sm">
                <div>
                  <dt>Camera windows</dt>
                  <dd className="font-semibold">{data.engagement.camera_windows ?? 'Unavailable'}</dd>
                </div>
                <div>
                  <dt>Microphone windows</dt>
                  <dd className="font-semibold">{data.engagement.microphone_windows ?? 'Unavailable'}</dd>
                </div>
              </dl>
            ) : (
              <p className="font-semibold">Not recorded for this session</p>
            )}
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
        <MissedQuestions sessionId={sessionId} />
        {import.meta.env.VITE_SOCRATIC_CHAT_ENABLED === 'true' && (
          <section aria-label="Study the session material" className="mt-10">
            <p className="mb-3 text-sm text-muted-foreground">Ask for guided help with the session material. For what was said in class, use the discussion catch-up above.</p>
            <SocraticChatPanel key={`material-${sessionId}`} sessionId={sessionId} />
          </section>
        )}
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
      <ReferenceAnswer correctAnswer={answer.correct_answer} keyPoints={answer.key_points} />
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
          <Sources path={`/student-reviews/${encodeURIComponent(sessionId)}/responses/${encodeURIComponent(answer.id)}/sources`} />
        </div>
      )}
    </article>
  )
}

function ReferenceAnswer({ correctAnswer, keyPoints = [] }: { correctAnswer?: string | null; keyPoints?: string[] }) {
  return (
    <div className="mt-3 rounded-md bg-muted/40 p-3">
      <p className="text-sm font-semibold">Reference answer</p>
      <p className="mt-1 whitespace-pre-wrap break-words text-sm">{correctAnswer || 'A reference answer is unavailable. Check the source or ask your lecturer.'}</p>
      {keyPoints.length > 0 && <><p className="mt-2 text-sm font-semibold">Key points to understand</p><ul className="list-disc space-y-1 pl-5 text-sm">{keyPoints.map((point, index) => <li key={index}>{point}</li>)}</ul></>}
    </div>
  )
}

function MissedQuestions({ sessionId }: { sessionId: string }) {
  const [offset, setOffset] = useState(0)
  const { data, error, status, retry } = useReviewResource<ReviewPage<MissedQuestion>>(
    `/student-reviews/${encodeURIComponent(sessionId)}/missed?limit=${PAGE_SIZE}&offset=${offset}`,
  )
  return (
    <section aria-labelledby="missed-heading" className="mt-10">
      <h2 id="missed-heading" className="mb-3 text-lg font-bold">Unanswered checkpoints</h2>
      <p className="mb-4 text-sm text-muted-foreground">Questions recorded as missed when they were delivered to you. Unanswered does not mean wrong.</p>
      {error ? <LoadError message={error} status={status} retry={retry} /> : !data ? <SkeletonRows label="Loading unanswered checkpoints" /> : data.items.length === 0 ? (
        <EmptyState title="No unanswered checkpoints recorded" />
      ) : <>
        <ol className="space-y-3">{data.items.map((question) => <li key={question.id}>
          <article className="rounded-lg border border-border bg-card px-5 py-4">
            <MetaLine items={[question.topic ?? 'No topic', 'Unanswered']} />
            <h3 className="mt-2 whitespace-pre-wrap font-semibold">{question.question}</h3>
            <ReferenceAnswer correctAnswer={question.correct_answer} keyPoints={question.key_points} />
            <MissedSources sessionId={sessionId} missedId={question.id} />
          </article>
        </li>)}</ol>
        <Pager offset={offset} total={data.total} onChange={setOffset} noun="unanswered checkpoints" />
      </>}
    </section>
  )
}

function MissedSources({ sessionId, missedId }: { sessionId: string; missedId: string }) {
  const [open, setOpen] = useState(false)
  // Load on expansion; do not fetch twenty source pages while reading the list.
  return <details className="mt-3" onToggle={event => setOpen(event.currentTarget.open)}>
    <summary className="cursor-pointer text-sm font-semibold text-primary">Show source for this unanswered checkpoint</summary>
    {open && <div className="mt-3"><Sources path={`/student-reviews/${encodeURIComponent(sessionId)}/missed/${encodeURIComponent(missedId)}/sources`} /></div>}
  </details>
}

function Sources({ path }: { path: string }) {
  const { data, error, retry } = useReviewResource<ReviewSources>(path)
  // Inside one answer, so a line rather than a full panel.
  if (error) {
    return (
      <p role="alert" className="text-sm text-muted-foreground">
        The source could not be loaded.{' '}
        <button type="button" onClick={retry} className="font-semibold text-primary underline underline-offset-2">
          Try again
        </button>
      </p>
    )
  }
  if (!data) return <p role="status" className="text-sm text-muted-foreground">Finding the source…</p>
  if (data.items.length === 0) {
    return (
      <p role="status" className="text-sm text-muted-foreground">
        The source is no longer kept. Ask your lecturer for the slides; nothing is made up to fill the gap.
      </p>
    )
  }
  return (
    <div role="group" aria-label="Where this question came from" className="space-y-2">
      {data.items.map((source) => (
        <blockquote key={source.chunk_id} className="rounded-md border-l-2 border-primary bg-muted/40 px-4 py-3">
          <MetaLine
            items={[
              <span key="title" className="font-semibold text-foreground">{source.material_title}</span>,
              source.source_page !== null ? `${source.source_label ?? 'Page or slide'} ${source.source_page}` : null,
              source.match === 'excerpt' ? 'The passage the question came from' : 'Same page, passage not confirmed',
            ]}
          />
          <p className="mt-2 whitespace-pre-wrap break-words text-sm">{source.text}</p>
        </blockquote>
      ))}
      {data.has_more && (
        <p className="text-sm text-muted-foreground">These are the first five matches. Your lecturer has the whole page.</p>
      )}
    </div>
  )
}

function LoadError({ message, retry, status }: { message: string; retry: () => void; status?: number }) {
  return (
    <ProblemState
      art={status === undefined ? 'offline' : problemArt(status)}
      title={status === 404 ? 'This review was not found' : 'This could not be loaded'}
      retry={status === 404 ? undefined : retry}
      action={
        status === 404 ? (
          <Link to="/student/reviews" className={buttonStyles({ intent: 'secondary' })}>
            Past sessions
          </Link>
        ) : undefined
      }
    >
      {message}
    </ProblemState>
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
