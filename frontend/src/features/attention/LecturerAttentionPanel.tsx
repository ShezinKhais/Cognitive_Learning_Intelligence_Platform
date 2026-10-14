import {
  engagementConfidenceLabel,
  engagementCounts,
  engagementScoreLabel,
  engagementStatusLabel,
  shortStudentId,
  signalLabel,
} from './lecturerAttention'

import type {
  EngagementStatus,
  LecturerEngagement,
} from './lecturerAttention'

interface LecturerAttentionPanelProps {
  students: LecturerEngagement[]
  loading: boolean
  error: string | null
  sessionStatus: string | undefined
}

function statusClass(
  status: EngagementStatus,
): string {
  if (status === 'engaged') {
    return 'bg-success/10 text-success'
  }

  if (status === 'at_risk') {
    return 'bg-warning/10 text-warning'
  }

  if (status === 'disengaged') {
    return 'bg-critical/10 text-critical'
  }

  return 'bg-muted text-muted-foreground'
}

export default function LecturerAttentionPanel({
  students,
  loading,
  error,
  sessionStatus,
}: LecturerAttentionPanelProps) {
  const counts =
    engagementCounts(students)

  const isActive =
    sessionStatus === 'active'

  return (
    <section className="rounded-xl border border-border bg-card p-6 lg:col-span-2">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-info">
            Phase 6
          </p>

          <h2 className="mt-1 text-lg font-semibold">
            Attention and engagement indicators
          </h2>

          <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
            These are privacy-preserving engagement
            estimates from the signals currently
            available to C.L.I.P. Missing camera or
            microphone signals are not counted as
            zero. These indicators do not measure
            comprehension.
          </p>
        </div>

        {loading && (
          <span
            role="status"
            className="text-sm text-muted-foreground"
          >
            Refreshing...
          </span>
        )}
      </div>

      {error && (
        <div
          role="alert"
          className="mt-4 rounded-md border border-warning/40 bg-warning/10 px-4 py-3 text-sm"
        >
          {students.length > 0
            ? `${error} Showing the last successfully loaded indicators.`
            : error}
        </div>
      )}

      {!isActive && (
        <div className="mt-5 rounded-md border border-border bg-muted/20 p-4">
          <p className="font-medium">
            Live indicators unavailable
          </p>

          <p className="mt-1 text-sm text-muted-foreground">
            Attention and engagement indicators are
            available while the session is active.
          </p>
        </div>
      )}

      {isActive &&
        students.length === 0 &&
        !loading &&
        !error && (
          <div className="mt-5 rounded-md border border-border bg-muted/20 p-4">
            <p className="font-medium">
              No engagement data yet
            </p>

            <p className="mt-1 text-sm text-muted-foreground">
              Indicators will appear when enough
              session activity is available. Missing
              optional signals are not treated as
              negative evidence.
            </p>
          </div>
        )}

      {students.length > 0 && (
        <>
          <dl className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            <div className="rounded-md border border-border bg-background p-3">
              <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Students
              </dt>

              <dd className="mt-1 text-xl font-semibold">
                {counts.total}
              </dd>
            </div>

            <div className="rounded-md border border-border bg-background p-3">
              <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Engaged
              </dt>

              <dd className="mt-1 text-xl font-semibold">
                {counts.engaged}
              </dd>
            </div>

            <div className="rounded-md border border-border bg-background p-3">
              <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                At risk
              </dt>

              <dd className="mt-1 text-xl font-semibold">
                {counts.atRisk}
              </dd>
            </div>

            <div className="rounded-md border border-border bg-background p-3">
              <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Disengaged
              </dt>

              <dd className="mt-1 text-xl font-semibold">
                {counts.disengaged}
              </dd>
            </div>

            <div className="rounded-md border border-border bg-background p-3">
              <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Insufficient data
              </dt>

              <dd className="mt-1 text-xl font-semibold">
                {counts.insufficientData}
              </dd>
            </div>
          </dl>

          <p className="mt-4 text-xs leading-5 text-muted-foreground">
            For privacy and contract safety, the current
            engagement API provides student IDs rather than
            display names. Shortened IDs are shown here
            instead of adding an unapproved identity lookup.
          </p>

          <div className="mt-5 grid gap-3 md:grid-cols-2">
            {students.map(
              (student) => (
                <article
                  key={student.student_id}
                  className="rounded-xl border border-border bg-background p-4"
                >
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                        Student
                      </p>

                      <p
                        className="mt-1 font-mono text-sm"
                        title={
                          student.student_id
                        }
                      >
                        {shortStudentId(
                          student.student_id,
                        )}
                      </p>
                    </div>

                    <span
                      className={`rounded-full px-3 py-1 text-xs font-semibold ${statusClass(
                        student.status,
                      )}`}
                    >
                      {engagementStatusLabel(
                        student.status,
                      )}
                    </span>
                  </div>

                  <dl className="mt-4 grid grid-cols-2 gap-3">
                    <div>
                      <dt className="text-xs text-muted-foreground">
                        Engagement score
                      </dt>

                      <dd className="mt-1 font-semibold">
                        {engagementScoreLabel(
                          student.score,
                        )}
                      </dd>
                    </div>

                    <div>
                      <dt className="text-xs text-muted-foreground">
                        Evidence coverage
                      </dt>

                      <dd className="mt-1 font-semibold">
                        {engagementConfidenceLabel(
                          student.confidence,
                        )}
                      </dd>
                    </div>
                  </dl>

                  <div className="mt-4">
                    <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      Signals contributing
                    </p>

                    {student.signals_available
                      .length > 0 ? (
                      <div className="mt-2 flex flex-wrap gap-2">
                        {student.signals_available.map(
                          (
                            signal,
                            index,
                          ) => (
                            <span
                              key={`${student.student_id}-${signal}-${index}`}
                              className="rounded-full border border-border px-2.5 py-1 text-xs"
                            >
                              {signalLabel(
                                signal,
                              )}
                            </span>
                          ),
                        )}
                      </div>
                    ) : (
                      <p className="mt-2 text-sm text-muted-foreground">
                        No contributing signals
                        are available yet.
                      </p>
                    )}
                  </div>

                  <p className="mt-4 text-xs text-muted-foreground">
                    Last computed:{' '}
                    {Number.isNaN(
                      Date.parse(
                        student.computed_at,
                      ),
                    )
                      ? 'Unavailable'
                      : new Date(
                          student.computed_at,
                        ).toLocaleTimeString()}
                  </p>
                </article>
              ),
            )}
          </div>
        </>
      )}
    </section>
  )
}