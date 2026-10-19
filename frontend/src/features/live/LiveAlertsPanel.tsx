import {
  useState,
} from 'react'

import { buttonStyles } from '../../components/ui/button'
import { Panel } from '../../components/ui/primitives'
import ConfidenceIndicator from '../intelligence/ConfidenceIndicator'
import ExplainabilityPanel from '../intelligence/ExplainabilityPanel'

import type {
  LiveAlert,
  LiveAlertKind,
  LiveSessionNotice,
} from './useLiveSession'

interface LiveAlertsPanelProps {
  alerts: LiveAlert[]
  sessionNotice: LiveSessionNotice | null
  onAcknowledge: (
    alertId: string,
  ) => Promise<void>
  className?: string
}

function alertKindLabel(
  kind: LiveAlertKind,
): string {
  if (kind === 'topic_difficulty') {
    return 'Topic difficulty'
  }

  if (kind === 'student_disengagement') {
    return 'Student disengagement'
  }

  return 'Breakout inactivity'
}

function noticeTitle(
  _notice: LiveSessionNotice,
): string {
  return 'Live session notice'
}

export default function LiveAlertsPanel({
  alerts,
  sessionNotice,
  onAcknowledge,
  className,
}: LiveAlertsPanelProps) {
  const [
    acknowledgingAlertId,
    setAcknowledgingAlertId,
  ] = useState<string | null>(null)

  const [
    acknowledgementError,
    setAcknowledgementError,
  ] = useState<string | null>(null)

  const hasAnything =
    sessionNotice !== null ||
    alerts.length > 0

  async function handleAcknowledge(
    alertId: string,
  ): Promise<void> {
    setAcknowledgementError(null)
    setAcknowledgingAlertId(alertId)

    try {
      await onAcknowledge(alertId)
    } catch {
      setAcknowledgementError(
        'The alert could not be acknowledged. Please try again.',
      )
    } finally {
      setAcknowledgingAlertId(null)
    }
  }

  return (
    <Panel
      className={className}
      title="Alerts"
      description="A topic the class is stuck on, a student who has gone quiet, or a room with no activity."
    >
      {acknowledgementError && (
        <div
          role="alert"
          className="mb-4 rounded-md border border-critical/30 bg-critical/10 px-3 py-2 text-sm text-critical"
        >
          {acknowledgementError}
        </div>
      )}

      {!hasAnything && (
        <p className="text-sm text-muted-foreground">
          Nothing needs you right now.
        </p>
      )}

      {sessionNotice && (
        <div
          role="alert"
          className="rounded-md border border-warning/40 bg-warning/10 p-4"
        >
          <p className="font-semibold">
            {noticeTitle(
              sessionNotice,
            )}
          </p>

          {sessionNotice.detail && (
            <p className="mt-1 text-sm">
              {
                sessionNotice.detail
              }
            </p>
          )}

          <p className="mt-2 text-xs text-muted-foreground">
            Code:{' '}
            {sessionNotice.code}
          </p>
        </div>
      )}

      {alerts.length > 0 && (
        <div className={sessionNotice ? 'mt-4 space-y-3' : 'space-y-3'}>
          {alerts.map(
            (alert) => {
              const hasIntelligenceDetails =
                alert.explanation !==
                  undefined ||
                alert.explanation_source !==
                  undefined ||
                alert.confidence_reasons !==
                  undefined ||
                alert.recommendation !==
                  undefined

              const isAcknowledging =
                acknowledgingAlertId ===
                alert.alert_id

              return (
                <article
                  key={alert.alert_id}
                  className="rounded-md border border-border p-4"
                >
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <p className="text-xs font-semibold text-muted-foreground">
                        {alertKindLabel(
                          alert.kind,
                        )}
                      </p>

                      <p className="mt-1 font-semibold">
                        {alert.message}
                      </p>
                    </div>

                    <ConfidenceIndicator
                      confidence={
                        alert.confidence
                      }
                    />
                  </div>

                  <p className="mt-3 text-sm text-muted-foreground">
                    {alert.reason}
                  </p>

                  {hasIntelligenceDetails && (
                    <div className="mt-4">
                      <ExplainabilityPanel
                        confidence={
                          alert.confidence
                        }
                        confidenceReasons={
                          alert.confidence_reasons
                        }
                        explanation={
                          alert.explanation
                        }
                        explanationSource={
                          alert.explanation_source
                        }
                        recommendation={
                          alert.recommendation
                        }
                      />
                    </div>
                  )}

                  <div className="mt-4 flex justify-end">
                    <button
                      type="button"
                      disabled={
                        acknowledgingAlertId !==
                        null
                      }
                      onClick={() => {
                        void handleAcknowledge(
                          alert.alert_id,
                        )
                      }}
                      className={buttonStyles({ intent: 'secondary' })}
                    >
                      {isAcknowledging
                        ? 'Acknowledging...'
                        : 'Acknowledge'}
                    </button>
                  </div>
                </article>
              )
            },
          )}
        </div>
      )}
    </Panel>
  )
}