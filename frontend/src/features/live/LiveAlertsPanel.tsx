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
}: LiveAlertsPanelProps) {
  const hasAnything =
    sessionNotice !== null ||
    alerts.length > 0

  return (
    <section className="rounded-xl border border-border bg-card p-6">
      <div>
        <h2 className="text-lg font-semibold">
          Alerts
        </h2>

        <p className="mt-1 text-sm text-muted-foreground">
          Live session issues and
          comprehension or engagement
          alerts appear here.
        </p>
      </div>

      {!hasAnything && (
        <div className="mt-5 rounded-md border border-border p-4">
          <p className="text-sm text-muted-foreground">
            No live alerts.
          </p>
        </div>
      )}

      {sessionNotice && (
        <div
          role="alert"
          className="mt-5 rounded-md border border-warning/40 bg-warning/10 p-4"
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
        <div className="mt-5 space-y-3">
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

              return (
                <article
                  key={alert.alert_id}
                  className="rounded-md border border-border p-4"
                >
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
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
                      onClick={() => {
                        void onAcknowledge(
                          alert.alert_id,
                        )
                      }}
                      className="rounded-md border border-border px-3 py-2 text-sm font-medium hover:bg-muted"
                    >
                      Acknowledge
                    </button>
                  </div>
                </article>
              )
            },
          )}
        </div>
      )}
    </section>
  )
}