import { useState } from 'react'
import { Link, useParams } from 'react-router'
import SignOutButton from '../components/SignOutButton'
import {
  comprehensionText,
  needsReview,
} from '../features/review/reviewDisplay'
import type {
  ReviewAnswer,
  ReviewPage,
  ReviewSession,
  ReviewSources,
  StudentReview,
} from '../features/review/reviewTypes'
import { useReviewResource } from '../features/review/useReviewResource'

const button =
  'inline-flex rounded-lg border border-border px-4 py-2 text-sm font-medium disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2'
const card = 'rounded-xl border border-border bg-card p-5'

export function StudentReviewHistoryPage() {
  const [offset, setOffset] = useState(0)
  const { data, error, retry } = useReviewResource<ReviewPage<ReviewSession>>(
    `/student-reviews?limit=20&offset=${offset}`,
  )
  return (
    <main className="mx-auto min-h-screen max-w-4xl space-y-6 px-6 py-10">
      <div className="flex items-center justify-between gap-4">
        <Link className="text-info underline" to="/student">
          Student workspace
        </Link>
        <SignOutButton />
      </div>
      <header>
        <p className="text-sm text-info">Your learning history</p>
        <h1 className="mt-2 text-3xl font-bold">Review past sessions</h1>
        <p className="mt-2 text-muted-foreground">
          Revisit your own answers and the source material after a session ends.
        </p>
      </header>
      {error ? (
        <LoadError message={error} retry={retry} />
      ) : !data ? (
        <p role="status">Loading session history…</p>
      ) : (
        <>
          {data.items.length === 0 ? (
            <p className={card}>
              No completed sessions are available for review yet.
            </p>
          ) : (
            <ul className="space-y-4">
              {data.items.map((session) => (
                <li key={session.id} className={card}>
                  <p className="text-sm text-muted-foreground">
                    {session.course_code}
                  </p>
                  <h2 className="mt-1 text-xl font-semibold">
                    <Link
                      className="text-info underline"
                      to={`/student/reviews/${session.id}`}
                    >
                      {session.title}
                    </Link>
                  </h2>
                  <p className="mt-2 text-sm">
                    {session.ended_at
                      ? `Ended ${new Date(session.ended_at).toLocaleString()}`
                      : 'Session ended'}
                  </p>
                </li>
              ))}
            </ul>
          )}
          <Pagination
            offset={offset}
            limit={20}
            total={data.total}
            change={setOffset}
          />
        </>
      )}
    </main>
  )
}

export default function StudentReviewPage() {
  const { sessionId } = useParams<{ sessionId: string }>()
  return sessionId ? (
    <Review key={sessionId} sessionId={sessionId} />
  ) : (
    <p role="alert">Session review unavailable.</p>
  )
}

function Review({ sessionId }: { sessionId: string }) {
  const [offset, setOffset] = useState(0)
  const [onlyReview, setOnlyReview] = useState(false)
  const { data, error, retry } = useReviewResource<StudentReview>(
    `/student-reviews/${encodeURIComponent(sessionId)}?limit=20&offset=${offset}`,
  )
  return (
    <main className="mx-auto min-h-screen max-w-4xl space-y-6 px-6 py-10">
      <div className="flex items-center justify-between gap-4">
        <Link className="text-info underline" to="/student/reviews">
          ← All session reviews
        </Link>
        <SignOutButton />
      </div>
      <h1 className="text-3xl font-bold">
        {data ? data.session.title : 'Session review'}
      </h1>
      {error ? (
        <LoadError message={error} retry={retry} />
      ) : !data ? (
        <p role="status">Loading your feedback…</p>
      ) : (
        <>
          <p className="text-muted-foreground">
            {data.session.course_code} · Only your answers are shown. No class
            rankings or combined learning score.
          </p>
          <section className={card} aria-labelledby="comprehension-heading">
            <h2 id="comprehension-heading" className="text-xl font-semibold">
              Comprehension — your answers
            </h2>
            <p className="mt-2">
              {data.questions_attempted} answered · {data.questions_missed}{' '}
              recorded unanswered
            </p>
            <p className="mt-2 text-sm text-muted-foreground">
              Unanswered questions are not marked wrong. Classifications are
              estimates from stored answer evaluations, not a measure of
              attention.
            </p>
          </section>
          <section className={card} aria-labelledby="engagement-heading">
            <h2 id="engagement-heading" className="text-xl font-semibold">
              Engagement — separate from understanding
            </h2>
            <p className="mt-2 font-medium">Insufficient verified data</p>
            <p className="mt-2 text-sm text-muted-foreground">
              {data.engagement.explanation}
            </p>
          </section>
          <section aria-labelledby="answers-heading" className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 id="answers-heading" className="text-xl font-semibold">
                Answer review
              </h2>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={onlyReview}
                  onChange={(event) => setOnlyReview(event.target.checked)}
                />
                Only answers needing review on this page
              </label>
            </div>
            {data.answers.length === 0 && (
              <p className={card}>
                No answers were recorded for you on this page. There is no
                comprehension result to infer.
              </p>
            )}
            {onlyReview &&
              data.answers.length > 0 &&
              !data.answers.some(needsReview) && (
                <p role="status">
                  No answers needing review on this page. Unclassified answers
                  can be seen by clearing the filter.
                </p>
              )}
            {data.answers
              .filter((answer) => !onlyReview || needsReview(answer))
              .map((answer) => (
                <Answer key={answer.id} answer={answer} sessionId={sessionId} />
              ))}
            <Pagination
              offset={offset}
              limit={20}
              total={data.total}
              change={setOffset}
            />
          </section>
        </>
      )}
    </main>
  )
}

function Answer({
  answer,
  sessionId,
}: {
  answer: ReviewAnswer
  sessionId: string
}) {
  const [showSources, setShowSources] = useState(false)
  const sourceId = `sources-${answer.id}`
  return (
    <article className={card}>
      <p className="text-sm text-info">
        {answer.topic || 'Topic not specified'}
      </p>
      <h3 className="mt-2 font-semibold whitespace-pre-wrap">
        {answer.question}
      </h3>
      <p className="mt-3 text-sm font-medium">Your answer</p>
      <p className="mt-1 whitespace-pre-wrap break-words">{answer.answer}</p>
      <p className="mt-3 font-medium">{comprehensionText(answer)}</p>
      {answer.confidence !== null && (
        <p className="mt-1 text-sm text-muted-foreground">
          Classification confidence: {Math.round(answer.confidence * 100)}% —
          not a grade.
        </p>
      )}
      {needsReview(answer) && (
        <p className="mt-2 text-sm">
          Revisit the source, explain the idea in your own words, and ask your
          lecturer about anything unclear.
        </p>
      )}
      <button
        className={`${button} mt-4`}
        aria-expanded={showSources}
        aria-controls={sourceId}
        onClick={() => setShowSources((value) => !value)}
      >
        {showSources
          ? 'Hide source chunks'
          : needsReview(answer)
            ? 'Review relevant source chunks'
            : 'View source chunks'}
      </button>
      {showSources && (
        <div id={sourceId} className="mt-4">
          <Sources sessionId={sessionId} responseId={answer.id} />
        </div>
      )}
    </article>
  )
}

function Sources({
  sessionId,
  responseId,
}: {
  sessionId: string
  responseId: string
}) {
  const { data, error, retry } = useReviewResource<ReviewSources>(
    `/student-reviews/${encodeURIComponent(sessionId)}/responses/${encodeURIComponent(responseId)}/sources`,
  )
  if (error) return <LoadError message={error} retry={retry} />
  if (!data) return <p role="status">Loading source chunks…</p>
  if (!data.items.length)
    return (
      <p role="status">
        Source chunks are unavailable or no longer retained. Ask your lecturer
        for the relevant material; no source has been invented.
      </p>
    )
  return (
    <section aria-label="Relevant source chunks" className="space-y-3">
      {data.items.map((source) => (
        <article
          key={source.chunk_id}
          id={`source-${responseId}-${source.chunk_id}`}
          className="rounded-lg border border-border p-4"
        >
          <h4 className="font-medium">
            <a
              className="text-info underline"
              href={`#source-${responseId}-${source.chunk_id}`}
            >
              {source.material_title}
              {source.source_page !== null
                ? ` · Page / slide ${source.source_page}`
                : ''}
            </a>
          </h4>
          <p className="mt-1 text-xs text-muted-foreground">
            {source.match === 'excerpt'
              ? 'Contains the question’s source excerpt'
              : 'Same-page context; exact source passage not verified'}
          </p>
          <p className="mt-3 whitespace-pre-wrap break-words text-sm">
            {source.text}
          </p>
        </article>
      ))}
      {data.has_more && (
        <p className="text-sm">
          Showing the first five matching chunks. Ask your lecturer for the
          complete page.
        </p>
      )}
    </section>
  )
}

function LoadError({ message, retry }: { message: string; retry: () => void }) {
  return (
    <div role="alert" className={card}>
      <p>{message}</p>
      <button className={`${button} mt-3`} onClick={retry}>
        Try again
      </button>
      <Link className="ml-4 text-info underline" to="/login">
        Sign in
      </Link>
    </div>
  )
}

function Pagination({
  offset,
  limit,
  total,
  change,
}: {
  offset: number
  limit: number
  total: number
  change: (value: number) => void
}) {
  return (
    <nav aria-label="Pagination" className="flex flex-wrap items-center gap-4">
      <button
        className={button}
        disabled={offset === 0}
        onClick={() => change(Math.max(0, offset - limit))}
      >
        Previous
      </button>
      <span className="text-sm">
        {total === 0
          ? '0 items'
          : `${Math.min(offset + 1, total)}–${Math.min(offset + limit, total)} of ${total}`}
      </span>
      <button
        className={button}
        disabled={offset + limit >= total}
        onClick={() => change(offset + limit)}
      >
        Next
      </button>
    </nav>
  )
}
