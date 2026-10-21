import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { BellRing, ExternalLink, Pause, Play, Square, X } from 'lucide-react'

import { ApiError } from '../../api'
import { buttonStyles } from '../../components/ui/button'
import ConfirmDialog from '../../components/ui/ConfirmDialog'
import { Tag } from '../../components/ui/primitives'
import { useDocumentTitle } from '../../components/ui/useDocumentTitle'
import { lecturerLiveSessionPath } from '../../teams/lecturerMeeting'
import { statusLabel, statusTone } from '../sessions/format'
import { getSession, listAllResponses, type SessionSummary } from '../sessions/sessionsApi'
import ManualQuestionTrigger from './ManualQuestionTrigger'
import {
  getSessionReadiness,
  runSessionAction,
  type SessionLifecycleAction,
  type SessionReadiness,
} from './sessionActions'
import { useLiveSession, type LiveAlert, type LiveAlertKind, type LiveQuestion } from './useLiveSession'

const ALERT_KIND: Record<LiveAlertKind, string> = {
  topic_difficulty: 'Topic difficulty',
  student_disengagement: 'Student disengagement',
  breakout_inactive: 'Quiet breakout room',
}

// The side panel is narrow, so it keeps the newest few. The rest are on the
// full dashboard.
const ALERTS_SHOWN = 3

function secondsUntilClose(question: LiveQuestion | null): number {
  const closesAt = question ? Date.parse(question.closes_at) : Number.NaN
  return Number.isNaN(closesAt) ? 0 : Math.max(0, Math.ceil((closesAt - Date.now()) / 1000))
}

/**
 * The lecturer's side panel in a Teams meeting: one narrow column with the
 * class controls, who is here and who has answered, and the latest alerts.
 * Everything else stays on the full dashboard, which it links to.
 *
 * A new alert pops up at the top of the panel and stays until the lecturer
 * dismisses or acknowledges it, since a toast that fades while they are
 * presenting is easy to miss.
 */
export default function LecturerMeetingPanel({ sessionId }: { sessionId: string }) {
  const { connectionStatus, sessionState, activeQuestion, closedQuestion, alerts, sessionNotice, acknowledgeAlert } =
    useLiveSession(sessionId)

  const [details, setDetails] = useState<SessionSummary | null>(null)
  const [readiness, setReadiness] = useState<SessionReadiness | null>(null)
  const [working, setWorking] = useState<SessionLifecycleAction | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [confirmingEnd, setConfirmingEnd] = useState(false)
  const [secondsRemaining, setSecondsRemaining] = useState(0)
  const [answered, setAnswered] = useState<number | null>(null)
  const [acknowledging, setAcknowledging] = useState<string | null>(null)

  useDocumentTitle(details ? `Live, ${details.title}` : 'Live session')

  useEffect(() => {
    let cancelled = false
    getSession(sessionId).then((found) => !cancelled && setDetails(found), () => undefined)
    return () => {
      cancelled = true
    }
  }, [sessionId])

  const status = sessionState?.status ?? details?.status
  const paused = sessionState?.paused ?? details?.paused ?? false

  useEffect(() => {
    if (status !== 'prepared') {
      setReadiness(null)
      return
    }
    let cancelled = false
    getSessionReadiness(sessionId).then((found) => !cancelled && setReadiness(found), () => undefined)
    return () => {
      cancelled = true
    }
  }, [sessionId, status])

  useEffect(() => {
    setSecondsRemaining(secondsUntilClose(activeQuestion))
    if (!activeQuestion) return
    const timer = window.setInterval(() => setSecondsRemaining(secondsUntilClose(activeQuestion)), 250)
    return () => window.clearInterval(timer)
  }, [activeQuestion])

  // Answers to the open question, re-read every few seconds as they arrive.
  // Once it closes, the close event carries the final count.
  const openQuestionId = activeQuestion?.question_id ?? null
  useEffect(() => {
    setAnswered(null)
    if (!openQuestionId) return
    let cancelled = false
    const load = () =>
      listAllResponses(sessionId).then(
        (found) => !cancelled && setAnswered(found.filter((r) => r.question_id === openQuestionId).length),
        () => undefined,
      )
    void load()
    const timer = window.setInterval(load, 4000)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [sessionId, openQuestionId])

  async function act(action: SessionLifecycleAction) {
    setActionError(null)
    setWorking(action)
    try {
      await runSessionAction(sessionId, action)
    } catch (error) {
      setActionError(error instanceof ApiError ? error.message : 'That could not be done. Try again.')
      if (action === 'start') {
        getSessionReadiness(sessionId).then(setReadiness, () => undefined)
      }
    } finally {
      setWorking(null)
    }
  }

  async function acknowledge(alertId: string) {
    setAcknowledging(alertId)
    try {
      await acknowledgeAlert(alertId)
    } catch {
      setActionError('The alert could not be acknowledged. Try again.')
    } finally {
      setAcknowledging(null)
    }
  }

  // The newest alert the lecturer has not dismissed yet.
  const dismissed = useRef(new Set<string>())
  const [, setDismissals] = useState(0)
  const popup = alerts.find((alert) => !dismissed.current.has(alert.alert_id)) ?? null
  function dismiss(alertId: string) {
    dismissed.current.add(alertId)
    setDismissals((count) => count + 1)
  }

  const busy = working !== null
  const live = status === 'active'
  const present = status === 'ended' || status === 'cancelled' ? 0 : (sessionState?.participant_count ?? null)
  const dashboard = lecturerLiveSessionPath(sessionId)

  return (
    <main className="min-h-screen bg-background px-3 py-4">
      <div className="mx-auto max-w-md space-y-4">
        <header className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-xs font-semibold text-muted-foreground">{details?.course_code ?? 'C.L.I.P'}</p>
            <h1 className="line-clamp-2 text-lg font-bold leading-snug">{details?.title ?? 'Live session'}</h1>
          </div>
          {status && (
            <Tag tone={statusTone({ status, paused })}>{statusLabel({ status, paused })}</Tag>
          )}
        </header>

        {connectionStatus !== 'connected' && status !== 'ended' && status !== 'cancelled' && (
          <p role="status" className="text-sm text-muted-foreground">
            {connectionStatus === 'connecting' ? 'Connecting…' : 'Reconnecting… the counts may be behind.'}
          </p>
        )}

        <AnimatePresence initial={false}>
          {popup && (
            <motion.div
              key={popup.alert_id}
              role="alert"
              initial={{ opacity: 0, y: -8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8, transition: { duration: 0.15 } }}
              transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
              className="rounded-lg border border-warning/50 bg-warning/10 p-3"
            >
              <div className="flex items-start gap-2.5">
                <BellRing size={17} aria-hidden className="mt-0.5 shrink-0 text-warning" />
                <div className="min-w-0 flex-1">
                  <p className="text-xs font-semibold text-muted-foreground">{ALERT_KIND[popup.kind]}</p>
                  <p className="mt-0.5 text-sm font-semibold">{popup.message}</p>
                </div>
                <button
                  type="button"
                  onClick={() => dismiss(popup.alert_id)}
                  className="rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
                >
                  <X size={15} aria-hidden />
                  <span className="sr-only">Dismiss</span>
                </button>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        <section aria-label="Class" className="rounded-lg border border-border bg-card p-3">
          <dl className="grid grid-cols-2 gap-3">
            <div>
              <dt className="text-xs text-muted-foreground">Present</dt>
              <dd className="text-2xl font-bold tabular-nums">{present ?? '-'}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">
                {activeQuestion ? 'Answered so far' : closedQuestion ? 'Answered last question' : 'Answered'}
              </dt>
              <dd className="text-2xl font-bold tabular-nums">
                {activeQuestion ? (
                  (answered ?? '-')
                ) : closedQuestion ? (
                  <>
                    {closedQuestion.respondents}
                    <span className="text-sm font-normal text-muted-foreground"> of {closedQuestion.eligible}</span>
                  </>
                ) : (
                  '-'
                )}
              </dd>
            </div>
          </dl>

          {activeQuestion && (
            <p className="mt-3 text-sm" aria-live="polite">
              <span className="font-semibold">Question open,</span>{' '}
              <span className="tabular-nums">{secondsRemaining}s</span> left
              <span className="mt-1 line-clamp-2 block text-muted-foreground">{activeQuestion.prompt}</span>
            </p>
          )}

          {status === 'prepared' && readiness && !readiness.ready && (
            <p className="mt-3 text-sm text-warning">
              {readiness.blockers[0]?.message ?? 'The class is not ready to start yet.'}
            </p>
          )}

          {actionError && (
            <p role="alert" className="mt-3 text-sm text-critical">
              {actionError}
            </p>
          )}

          <div className="mt-3 flex flex-wrap gap-2">
            {status === 'prepared' && (
              <button
                type="button"
                className={buttonStyles()}
                disabled={busy || readiness?.ready !== true}
                onClick={() => void act('start')}
              >
                <Play size={15} aria-hidden />
                {working === 'start' ? 'Starting…' : 'Start the class'}
              </button>
            )}
            {live &&
              (paused ? (
                <button type="button" className={buttonStyles({ intent: 'secondary' })} disabled={busy} onClick={() => void act('resume')}>
                  <Play size={15} aria-hidden />
                  {working === 'resume' ? 'Resuming…' : 'Resume'}
                </button>
              ) : (
                <button type="button" className={buttonStyles({ intent: 'secondary' })} disabled={busy} onClick={() => void act('pause')}>
                  <Pause size={15} aria-hidden />
                  {working === 'pause' ? 'Pausing…' : 'Pause'}
                </button>
              ))}
            {(live || status === 'prepared') && (
              <button type="button" className={buttonStyles({ intent: 'danger' })} disabled={busy} onClick={() => setConfirmingEnd(true)}>
                <Square size={14} aria-hidden />
                {status === 'prepared' ? 'Cancel' : working === 'end' ? 'Ending…' : 'End class'}
              </button>
            )}
          </div>

          {live && (
            <ManualQuestionTrigger
              sessionId={sessionId}
              enabled={connectionStatus === 'connected' && !paused && activeQuestion === null}
            />
          )}

          {(status === 'ended' || status === 'cancelled') && (
            <p className="mt-3 text-sm text-muted-foreground">This session is no longer running.</p>
          )}
        </section>

        <section aria-labelledby="panel-alerts" className="rounded-lg border border-border bg-card p-3">
          <h2 id="panel-alerts" className="font-bold">
            Alerts
          </h2>
          {sessionNotice && <p className="mt-2 text-sm text-warning">{sessionNotice.detail ?? sessionNotice.code}</p>}
          {alerts.length === 0 ? (
            <p className="mt-2 text-sm text-muted-foreground">Nothing needs you right now.</p>
          ) : (
            <ul className="mt-2 space-y-2">
              {alerts.slice(0, ALERTS_SHOWN).map((alert) => (
                <AlertRow
                  key={alert.alert_id}
                  alert={alert}
                  busy={acknowledging !== null}
                  acknowledging={acknowledging === alert.alert_id}
                  onAcknowledge={() => {
                    dismiss(alert.alert_id)
                    void acknowledge(alert.alert_id)
                  }}
                />
              ))}
            </ul>
          )}
          {alerts.length > ALERTS_SHOWN && (
            <p className="mt-2 text-xs text-muted-foreground">
              {alerts.length - ALERTS_SHOWN} more on the full dashboard.
            </p>
          )}
        </section>

        <a
          href={dashboard}
          target="_blank"
          rel="noopener noreferrer"
          className={buttonStyles({ intent: 'secondary', className: 'w-full' })}
        >
          Open the full dashboard
          <ExternalLink size={14} aria-hidden />
        </a>
      </div>

      <ConfirmDialog
        open={confirmingEnd}
        title={status === 'prepared' ? 'Cancel this session?' : 'End the class?'}
        confirmLabel={status === 'prepared' ? 'Cancel the session' : 'End the class'}
        cancelLabel={status === 'prepared' ? 'Keep it' : 'Keep teaching'}
        busy={working === 'end'}
        onCancel={() => setConfirmingEnd(false)}
        onConfirm={() => {
          void act('end').finally(() => setConfirmingEnd(false))
        }}
      >
        {status === 'prepared' ? (
          <p>It will not run, and students can no longer join it. This cannot be undone.</p>
        ) : (
          <p>Students are disconnected and no more questions are sent. Answers so far are kept for the report.</p>
        )}
      </ConfirmDialog>
    </main>
  )
}

function AlertRow({
  alert,
  busy,
  acknowledging,
  onAcknowledge,
}: {
  alert: LiveAlert
  busy: boolean
  acknowledging: boolean
  onAcknowledge: () => void
}) {
  return (
    <li className="rounded-md border border-border p-2.5">
      <p className="text-xs font-semibold text-muted-foreground">{ALERT_KIND[alert.kind]}</p>
      <p className="mt-0.5 text-sm font-semibold">{alert.message}</p>
      <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{alert.reason}</p>
      <button
        type="button"
        disabled={busy}
        onClick={onAcknowledge}
        className={buttonStyles({ intent: 'quiet', className: 'mt-1 -ml-3 px-3 py-1' })}
      >
        {acknowledging ? 'Acknowledging…' : 'Acknowledge'}
      </button>
    </li>
  )
}
