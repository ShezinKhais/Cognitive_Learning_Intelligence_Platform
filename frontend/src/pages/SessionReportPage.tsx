import { useEffect, useState } from 'react'
import { FileText } from 'lucide-react'
import { Link, useParams } from 'react-router'

import { ApiError } from '../api'
import { buttonStyles } from '../components/ui/button'
import { EmptyState, PageBody, PageHeader, Panel, Tag } from '../components/ui/primitives'
import { difficultyLabel, type TopicDifficulty } from '../features/intelligence/topicRecovery'
import { getSessionTopics } from '../features/intelligence/topicRecoveryApi'
import SessionStrip, { StripLegend } from '../features/sessions/SessionStrip'
import { formatWhen, statusLabel, statusTone } from '../features/sessions/format'
import {
  getReport,
  getSession,
  listAllResponses,
  openReportPdf,
  requestReport,
  type ReportJob,
  type SessionResponse,
  type SessionSummary,
} from '../features/sessions/sessionsApi'
import { stripFromResponses } from '../features/sessions/strip'

const POLL_MS = 2000

export default function SessionReportPage() {
  const { sessionId = '' } = useParams()
  const [session, setSession] = useState<SessionSummary | null>(null)
  const [responses, setResponses] = useState<SessionResponse[] | null>(null)
  const [topics, setTopics] = useState<TopicDifficulty[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    Promise.all([getSession(sessionId), listAllResponses(sessionId), getSessionTopics(sessionId).catch(() => [])])
      .then(([found, answers, hardest]) => {
        if (cancelled) return
        setSession(found)
        setResponses(answers)
        setTopics(hardest)
      })
      .catch((caught: unknown) => {
        if (!cancelled) setError(caught instanceof ApiError ? caught.message : 'This session could not be loaded.')
      })
    return () => {
      cancelled = true
    }
  }, [sessionId])

  if (error) {
    return (
      <PageBody>
        <EmptyState title="This session could not be loaded" action={<Link to="/lecturer/sessions" className={buttonStyles({ intent: 'secondary' })}>Back to sessions</Link>}>
          {error}
        </EmptyState>
      </PageBody>
    )
  }
  if (!session || !responses || !topics) {
    return <PageBody><p role="status" className="text-muted-foreground">Loading the session…</p></PageBody>
  }

  const strip = stripFromResponses(responses)
  const marked = responses.filter((r) => r.is_correct !== null)
  const right = marked.filter((r) => r.is_correct).length

  return (
    <>
      <PageHeader
        title={session.title}
        tabTitle={`Report, ${session.title}`}
        back={{ to: '/lecturer/sessions', label: 'Sessions' }}
        description={`${session.course_code}, ${formatWhen(session.ended_at ?? session.starts_at)}`}
        actions={
          session.status === 'active' && (
            <Link to={`/lecturer/sessions/${session.id}/live`} className={buttonStyles({ intent: 'secondary' })}>
              Open live view
            </Link>
          )
        }
      >
        <div className="mt-3">
          <Tag tone={statusTone(session)}>{statusLabel(session)}</Tag>
        </div>
      </PageHeader>
      <PageBody>
        <Panel title="How the class answered" className="mb-6">
          {strip.length === 0 ? (
            <p className="text-muted-foreground">No answers were stored for this session.</p>
          ) : (
            <div className="flex flex-wrap items-end justify-between gap-6">
              <div>
                <SessionStrip questions={strip} />
                <div className="mt-3">
                  <StripLegend />
                </div>
              </div>
              <dl className="grid grid-cols-3 gap-6 text-right">
                <Figure label="Questions" value={strip.length} />
                <Figure label="Answers" value={responses.length} />
                <Figure label="Right" value={marked.length ? `${Math.round((right / marked.length) * 100)}%` : 'None marked'} />
              </dl>
            </div>
          )}
        </Panel>

        <div className="grid gap-6 lg:grid-cols-[1.4fr_1fr]">
          <Panel title="Topics" description="Hardest first, from how each answer was marked.">
            <TopicTable topics={topics} />
          </Panel>
          <ReportPanel sessionId={session.id} />
        </div>
      </PageBody>
    </>
  )
}

function Figure({ label, value }: { label: string; value: number | string }) {
  return (
    <div>
      <dt className="text-sm text-muted-foreground">{label}</dt>
      <dd className="text-2xl font-bold">{value}</dd>
    </div>
  )
}

function TopicTable({ topics }: { topics: TopicDifficulty[] }) {
  if (topics.length === 0) return <p className="text-muted-foreground">No topic has marked answers yet.</p>
  return (
    <ul className="divide-y divide-border">
      {topics.map((topic) => {
        const total = topic.mastered + topic.partial + topic.struggling
        const pct = (n: number) => `${total ? (n / total) * 100 : 0}%`
        return (
          <li key={topic.topic} className="py-3 first:pt-0 last:pb-0">
            <div className="flex items-baseline justify-between gap-3">
              <span className="font-semibold">{topic.topic}</span>
              <span className="text-sm text-muted-foreground">{difficultyLabel(topic.level)}</span>
            </div>
            <div className="mt-2 flex h-2 overflow-hidden rounded-full bg-muted" aria-hidden>
              <span className="bg-success" style={{ width: pct(topic.mastered) }} />
              <span className="bg-warning" style={{ width: pct(topic.partial) }} />
              <span className="bg-critical" style={{ width: pct(topic.struggling) }} />
            </div>
            <p className="mt-1.5 text-sm text-muted-foreground">
              {topic.mastered} mastered, {topic.partial} partly, {topic.struggling} struggling
              {topic.uncertain > 0 && `, ${topic.uncertain} uncertain`}
            </p>
          </li>
        )
      })}
    </ul>
  )
}

function ReportPanel({ sessionId }: { sessionId: string }) {
  const [job, setJob] = useState<ReportJob | null>(null)
  const [error, setError] = useState<string | null>(null)
  const pending = job?.status === 'queued' || job?.status === 'running'

  useEffect(() => {
    if (!job || !pending) return
    const timer = setTimeout(() => {
      getReport(job.report_id).then(setJob, () => setError('The report stopped answering. Try building it again.'))
    }, POLL_MS)
    return () => clearTimeout(timer)
  }, [job, pending])

  async function build() {
    setError(null)
    try {
      setJob(await requestReport(sessionId))
    } catch (caught: unknown) {
      setError(caught instanceof ApiError ? caught.message : 'The report could not be started.')
    }
  }

  const report = job?.status === 'ready' ? job.report : null

  return (
    <Panel
      title="Session report"
      description="Participation, topics and alerts, as a page you can keep or share as a PDF."
    >
      {!job && (
        <button type="button" className={buttonStyles()} onClick={build}>
          Build the report
        </button>
      )}
      {pending && <p role="status" className="text-muted-foreground">Building the report…</p>}
      {job?.status === 'failed' && (
        <p role="alert" className="text-critical">{job.error ?? job.message ?? 'The report could not be built.'}</p>
      )}
      {error && <p role="alert" className="mt-2 text-critical">{error}</p>}
      {report && (
        <div className="space-y-4">
          <dl className="grid grid-cols-2 gap-4">
            <Figure label="Students" value={report.participation.students} />
            <Figure label="Answers" value={report.participation.answers} />
            <Figure label="Missed answers" value={report.participation.missed_answers} />
            <Figure label="Refocus prompts" value={report.participation.attention_prompts} />
          </dl>
          {report.alerts.length > 0 && (
            <div>
              <h3 className="font-semibold">Alerts raised</h3>
              <ul className="mt-2 space-y-2 text-sm">
                {report.alerts.map((alert) => (
                  <li key={alert.alert_id} className="rounded-md border border-border px-3 py-2">
                    {alert.message}
                  </li>
                ))}
              </ul>
            </div>
          )}
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className={buttonStyles()}
              onClick={() => job && openReportPdf(job.report_id).catch(() => setError('The PDF could not be opened.'))}
            >
              <FileText size={16} aria-hidden />
              Open the PDF
            </button>
            <button type="button" className={buttonStyles({ intent: 'quiet' })} onClick={build}>
              Build again
            </button>
          </div>
        </div>
      )}
    </Panel>
  )
}
