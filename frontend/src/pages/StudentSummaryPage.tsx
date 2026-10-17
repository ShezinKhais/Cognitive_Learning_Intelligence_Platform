import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router'

import { ApiError } from '../api'
import { buttonStyles } from '../components/ui/button'
import { EmptyState, PageBody, PageHeader, Panel, Tag, type Tone } from '../components/ui/primitives'
import SessionStrip, { StripLegend } from '../features/sessions/SessionStrip'
import { formatWhen } from '../features/sessions/format'
import {
  getSession,
  getStudentSummary,
  listAllResponses,
  type SessionResponse,
  type SessionSummary,
  type StudentSummary,
} from '../features/sessions/sessionsApi'
import { stripFromResponses } from '../features/sessions/strip'

const TOPIC_TONE: Record<string, Tone> = { mastered: 'good', partial: 'mixed', struggling: 'poor' }
const TOPIC_WORD: Record<string, string> = { mastered: 'Mastered', partial: 'Partly there', struggling: 'Revisit this' }

/** A student's own look back at one session: their answers, and their
 * topics once the summary route is built. Nothing about anyone else. */
export default function StudentSummaryPage() {
  const { sessionId = '' } = useParams()
  const [session, setSession] = useState<SessionSummary | null>(null)
  const [answers, setAnswers] = useState<SessionResponse[] | null>(null)
  const [summary, setSummary] = useState<StudentSummary | null | 'none'>('none')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    async function load() {
      const [found, own] = await Promise.all([getSession(sessionId), listAllResponses(sessionId)])
      if (cancelled) return
      setSession(found)
      setAnswers(own)
      const studentId = own[0]?.student_id
      setSummary(studentId ? await getStudentSummary(sessionId, studentId).catch(() => null) : null)
    }
    load().catch((caught: unknown) => {
      if (!cancelled) setError(caught instanceof ApiError ? caught.message : 'This session could not be loaded.')
    })
    return () => {
      cancelled = true
    }
  }, [sessionId])

  if (error) {
    return (
      <PageBody>
        <EmptyState title="This session could not be loaded" action={<Link to="/student" className={buttonStyles({ intent: 'secondary' })}>Back to my sessions</Link>}>
          {error}
        </EmptyState>
      </PageBody>
    )
  }
  if (!session || !answers) {
    return <PageBody><p role="status" className="text-muted-foreground">Loading your session…</p></PageBody>
  }

  const strip = stripFromResponses(answers)
  const right = answers.filter((a) => a.is_correct === true).length
  const marked = answers.filter((a) => a.is_correct !== null).length

  return (
    <>
      <PageHeader
        title={session.title}
        tabTitle={`How you did, ${session.title}`}
        back={{ to: '/student', label: 'My sessions' }}
        description={`${session.course_code}, ${formatWhen(session.ended_at ?? session.starts_at)}`}
        actions={
          <Link to={`/student/reviews/${sessionId}`} className={buttonStyles({ intent: 'secondary' })}>
            Go over each answer
          </Link>
        }
      />
      <PageBody>
        <div className="grid gap-6 lg:grid-cols-[1.3fr_1fr]">
          <Panel title="Your answers" description="Only you and your lecturer can see these.">
            {answers.length === 0 ? (
              <p className="text-muted-foreground">You did not answer any questions in this session.</p>
            ) : (
              <>
                <p className="text-lg">
                  <strong>{answers.length}</strong> {answers.length === 1 ? 'answer' : 'answers'}
                  {marked > 0 && (
                    <>
                      , <strong>{right}</strong> right of {marked} marked
                    </>
                  )}
                </p>
                <div className="mt-4">
                  <SessionStrip questions={strip} />
                </div>
                <div className="mt-3">
                  <StripLegend />
                </div>
              </>
            )}
          </Panel>

          <Panel title="Your topics" description="What to revisit before the next class.">
            {summary === 'none' && <p role="status" className="text-muted-foreground">Loading…</p>}
            {summary === null && (
              <p className="text-muted-foreground">
                A topic by topic summary will appear here once personal summaries are switched on. Your answers on
                the left are already saved.
              </p>
            )}
            {summary && summary !== 'none' && <TopicList topics={summary.comprehension_by_topic} />}
          </Panel>
        </div>

        {summary && summary !== 'none' && (summary.action_items?.length ?? 0) > 0 && (
          <Panel title="Before the next class" className="mt-6">
            <ul className="space-y-2.5">
              {summary.action_items!.map((item, index) => (
                <li key={`${item.kind}-${item.topic ?? index}`} className="flex gap-3">
                  <span aria-hidden className="mt-2.5 h-px w-3 shrink-0 bg-muted-foreground" />
                  <span>{item.text}</span>
                </li>
              ))}
            </ul>
          </Panel>
        )}
      </PageBody>
    </>
  )
}

function TopicList({ topics }: { topics: Record<string, string> }) {
  const entries = Object.entries(topics)
  if (entries.length === 0) return <p className="text-muted-foreground">No topic had enough marked answers to say.</p>
  return (
    <ul className="divide-y divide-border">
      {entries.map(([topic, level]) => (
        <li key={topic} className="flex items-center justify-between gap-3 py-2.5">
          <span>{topic}</span>
          <Tag tone={TOPIC_TONE[level] ?? 'neutral'}>{TOPIC_WORD[level] ?? level}</Tag>
        </li>
      ))}
    </ul>
  )
}
