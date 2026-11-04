import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router'

import { EmptyState, MetaLine, PageBody, PageHeader, Panel, SkeletonRows } from '../components/ui/primitives'
import { ProblemState } from '../components/ui/ProblemState'
import { problemArt, problemOf, type Problem } from '../components/ui/problem'
import SegmentedTabs from '../components/ui/SegmentedTabs'
import { answerTrend, coursesOf, percent, quietReason } from '../features/sessions/engagementHistory'
import {
  getEngagementHistory,
  type EngagementHistory,
  type SessionEngagement,
} from '../features/sessions/engagementHistoryApi'

const ALL = 'all'

/** How each class engaged across the term, and who to check in with. */
export default function LecturerEngagementHistoryPage() {
  const [history, setHistory] = useState<EngagementHistory | null>(null)
  const [error, setError] = useState<Problem | null>(null)
  const [course, setCourse] = useState<string>(ALL)

  const load = useCallback(() => {
    setError(null)
    getEngagementHistory().then(setHistory, (caught: unknown) =>
      setError(problemOf(caught, 'Check your connection and try again.')),
    )
  }, [])
  useEffect(load, [load])

  const courses = useMemo(() => (history ? coursesOf(history.sessions) : []), [history])
  const sessions = useMemo(
    () => history?.sessions.filter((row) => course === ALL || row.course_code === course) ?? [],
    [history, course],
  )
  const quiet = useMemo(
    () => history?.quiet.filter((row) => course === ALL || row.course_code === course) ?? [],
    [history, course],
  )
  const trend = answerTrend(sessions)

  return (
    <>
      <PageHeader
        title="Engagement history"
        description="How your classes engaged across the term, built from who joined and how they answered."
        actions={
          courses.length > 1 ? (
            <SegmentedTabs
              label="Course"
              value={course}
              onChange={setCourse}
              segments={[{ key: ALL, label: 'All' }, ...courses.map((code) => ({ key: code, label: code }))]}
            />
          ) : undefined
        }
      />
      <PageBody>
        {error ? (
          <ProblemState art={problemArt(error.cause)} title="The history could not be loaded" retry={load}>
            {error.message}
          </ProblemState>
        ) : !history ? (
          <SkeletonRows label="Loading engagement history" />
        ) : history.sessions.length === 0 ? (
          <EmptyState art="lecture" title="No finished classes yet">
            Each class appears here once it ends.{' '}
            <Link to="/lecturer/sessions" className="font-semibold underline">
              Go to your sessions
            </Link>
          </EmptyState>
        ) : (
          <div className="grid gap-4 lg:grid-cols-[1fr_20rem]">
            <Panel
              title="Classes"
              description={
                trend === null
                  ? `${sessions.length} finished`
                  : `${sessions.length} finished. ${trendWords(trend)}`
              }
            >
              <ul className="divide-y divide-border">
                {sessions.map((row) => (
                  <SessionRow key={row.session_id} row={row} />
                ))}
              </ul>
            </Panel>

            <Panel
              title="Check in with"
              description={`Only you and administrators see this. It looks at the last ${history.recent_window} classes of each course.`}
            >
              {quiet.length === 0 ? (
                <p className="text-sm text-muted-foreground">Nobody has gone quiet across those classes.</p>
              ) : (
                <ul className="space-y-3">
                  {quiet.map((student) => (
                    <li key={student.student_id}>
                      <p className="font-semibold">{student.name}</p>
                      <MetaLine items={[student.course_code, quietReason(student)]} />
                    </li>
                  ))}
                </ul>
              )}
              <p className="mt-4 text-xs text-muted-foreground">
                A prompt to talk to them, not a mark. Students with an approved special consideration are never listed.
              </p>
            </Panel>
          </div>
        )}
      </PageBody>
    </>
  )
}

function trendWords(trend: number): string {
  const points = Math.abs(Math.round(trend * 100))
  if (points === 0) return 'The latest class answered about as much as the ones before it.'
  const unit = points === 1 ? 'point' : 'points'
  return `The latest class answered ${points} percentage ${unit} ${trend > 0 ? 'more' : 'less'} than the ones before it.`
}

function SessionRow({ row }: { row: SessionEngagement }) {
  const held = new Date(row.held_at).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
  return (
    <li className="py-3 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3">
        <Link to={`/lecturer/sessions/${row.session_id}/results`} className="font-semibold hover:underline">
          {row.title}
        </Link>
        <span className="text-sm text-muted-foreground">{held}</span>
      </div>
      <MetaLine
        items={[row.course_code, `${row.present} joined`, `${row.checkpoints} checkpoint${row.checkpoints === 1 ? '' : 's'}`]}
      />
      <dl className="mt-2 grid grid-cols-3 gap-3 text-sm">
        <Measure label="Answered" value={row.answer_rate} />
        <Measure label="Right" value={row.correct_rate} />
        <Measure label="On screen" value={row.on_screen} hint="Shown when 3 or more students turned it on" />
      </dl>
    </li>
  )
}

function Measure({ label, value, hint }: { label: string; value: number | null; hint?: string }) {
  return (
    <div title={value === null ? hint : undefined}>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="font-semibold tabular-nums">{percent(value)}</dd>
      <div aria-hidden className="mt-1 h-1 rounded-full bg-muted">
        {value !== null && (
          <div className="h-1 rounded-full bg-primary" style={{ width: `${Math.round(value * 100)}%` }} />
        )}
      </div>
    </div>
  )
}
