import {
  useEffect,
  useState,
} from 'react'
import {
  Download,
  FileText,
  RefreshCw,
} from 'lucide-react'
import {
  Link,
  useParams,
} from 'react-router'

import {
  ApiError,
  clearAccessToken,
} from '../api'
import SignOutButton from '../components/SignOutButton'
import {
  reportFailureMessage,
  reportIsReady,
  reportStatusLabel,
  type ReportJob,
  type ReportTopicDifficulty,
} from '../features/reports/sessionReports'
import {
  downloadSessionReportPdf,
  getSessionReport,
  requestSessionReport,
} from '../features/reports/sessionReportsApi'

function dateLabel(
  value: string | null,
): string {
  if (!value) {
    return 'Unavailable'
  }

  const parsed =
    Date.parse(value)

  if (Number.isNaN(parsed)) {
    return 'Unavailable'
  }

  return new Date(
    parsed,
  ).toLocaleString()
}

function topicLevelLabel(
  topic: ReportTopicDifficulty,
): string {
  if (topic.level === 'easy') {
    return 'Easy'
  }

  if (topic.level === 'medium') {
    return 'Medium'
  }

  if (topic.level === 'hard') {
    return 'Hard'
  }

  return 'Not enough data'
}

function topicScoreLabel(
  score: number | null,
): string {
  if (
    score === null ||
    !Number.isFinite(score)
  ) {
    return 'Unavailable'
  }

  return score.toFixed(2)
}

export default function LecturerSessionReportPage() {
  const { sessionId } =
    useParams<{
      sessionId: string
    }>()

  const [
    job,
    setJob,
  ] =
    useState<ReportJob | null>(
      null,
    )

  const [
    loading,
    setLoading,
  ] = useState(false)

  const [
    downloading,
    setDownloading,
  ] = useState(false)

  const [
    error,
    setError,
  ] =
    useState<string | null>(
      null,
    )

  useEffect(() => {
    if (
      !job ||
      (
        job.status !== 'queued' &&
        job.status !== 'running'
      )
    ) {
      return
    }

    const reportId =
      job.report_id

    let active = true

    let timer:
      | number
      | undefined

    function scheduleNextPoll() {
      if (!active) {
        return
      }

      timer =
        window.setTimeout(
          () => {
            void pollReport()
          },
          2000,
        )
    }

    async function pollReport() {
      if (!active) {
        return
      }

      try {
        const updated =
          await getSessionReport(
            reportId,
          )

        if (!active) {
          return
        }

        setJob(updated)
        setError(null)

        if (
          updated.status ===
            'queued' ||
          updated.status ===
            'running'
        ) {
          scheduleNextPoll()
        }
      } catch (
        caught: unknown
      ) {
        if (!active) {
          return
        }

        if (
          caught instanceof ApiError &&
          caught.status === 401
        ) {
          clearAccessToken()

          window.location.assign(
            '/login',
          )

          return
        }

        if (
          caught instanceof ApiError &&
          caught.status === 404
        ) {
          setJob(null)

          setError(
            'This report is no longer available. It may have expired or the server may have restarted. Generate the report again.',
          )

          return
        }

        if (
          caught instanceof ApiError &&
          caught.status === 403
        ) {
          setError(
            caught.message,
          )

          return
        }

        setError(
          caught instanceof ApiError
            ? `${caught.message} Automatic status checks will continue.`
            : 'The report status could not be refreshed. Automatic status checks will continue.',
        )

        scheduleNextPoll()
      }
    }

    scheduleNextPoll()

    return () => {
      active = false

      if (
        timer !== undefined
      ) {
        window.clearTimeout(
          timer,
        )
      }
    }
  }, [job])

  async function generateReport() {
    if (!sessionId) {
      return
    }

    setLoading(true)
    setError(null)

    try {
      const requested =
        await requestSessionReport(
          sessionId,
        )

      setJob(requested)
    } catch (
      caught: unknown
    ) {
      if (
        caught instanceof ApiError &&
        caught.status === 401
      ) {
        clearAccessToken()

        window.location.assign(
          '/login',
        )

        return
      }

      setError(
        caught instanceof ApiError
          ? caught.message
          : 'The session report could not be requested.',
      )
    } finally {
      setLoading(false)
    }
  }

  async function refreshReport() {
    if (!job) {
      return
    }

    setLoading(true)
    setError(null)

    try {
      const updated =
        await getSessionReport(
          job.report_id,
        )

      setJob(updated)
    } catch (
      caught: unknown
    ) {
      if (
        caught instanceof ApiError &&
        caught.status === 401
      ) {
        clearAccessToken()

        window.location.assign(
          '/login',
        )

        return
      }

      if (
        caught instanceof ApiError &&
        caught.status === 404
      ) {
        setJob(null)

        setError(
          'This report is no longer available. It may have expired or the server may have restarted. Generate the report again.',
        )

        return
      }

      setError(
        caught instanceof ApiError
          ? caught.message
          : 'The report status could not be refreshed.',
      )
    } finally {
      setLoading(false)
    }
  }

  async function downloadPdf() {
    if (
      !job ||
      !reportIsReady(job)
    ) {
      return
    }

    setDownloading(true)
    setError(null)

    try {
      const download =
        await downloadSessionReportPdf(
          job.report_id,
        )

      const url =
        window.URL.createObjectURL(
          download.blob,
        )

      const link =
        document.createElement(
          'a',
        )

      link.href = url
      link.download =
        download.filename

      document.body.appendChild(
        link,
      )

      link.click()
      link.remove()

      window.URL.revokeObjectURL(
        url,
      )
    } catch (
      caught: unknown
    ) {
      if (
        caught instanceof ApiError &&
        caught.status === 401
      ) {
        clearAccessToken()

        window.location.assign(
          '/login',
        )

        return
      }

      if (
        caught instanceof ApiError &&
        caught.status === 404
      ) {
        setJob(null)

        setError(
          'This report is no longer available. Generate it again before downloading a PDF.',
        )

        return
      }

      setError(
        caught instanceof ApiError
          ? caught.message
          : 'The PDF could not be downloaded.',
      )
    } finally {
      setDownloading(false)
    }
  }

  const report =
    job?.report ?? null

  const failure =
    job
      ? reportFailureMessage(
          job,
        )
      : null

  const canGenerate =
    !job ||
    job.status === 'failed'

  return (
    <main className="min-h-screen bg-background">
      <header className="border-b border-border bg-card">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-5 py-4 sm:px-8">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
              C.L.I.P lecturer
              workspace
            </p>

            <h1 className="mt-1 text-xl font-bold text-card-foreground">
              Session Report
            </h1>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            {sessionId && (
              <Link
                to={`/lecturer/sessions/${encodeURIComponent(
                  sessionId,
                )}/live`}
                className="rounded-lg border border-border px-3 py-2 text-sm font-medium hover:bg-muted"
              >
                Live workspace
              </Link>
            )}

            <Link
              to="/lecturer/sessions"
              className="rounded-lg border border-border px-3 py-2 text-sm font-medium hover:bg-muted"
            >
              Sessions
            </Link>

            <SignOutButton />
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-6xl px-5 py-8 sm:px-8">
        <section className="rounded-2xl border border-border bg-card p-6 shadow-[var(--shadow-card)]">
          <div className="flex flex-wrap items-start justify-between gap-5">
            <div className="flex items-start gap-3">
              <div className="grid size-11 shrink-0 place-items-center rounded-xl bg-info/10 text-info">
                <FileText
                  aria-hidden="true"
                  size={22}
                />
              </div>

              <div>
                <h2 className="text-2xl font-semibold tracking-tight">
                  Staff session
                  report
                </h2>

                <p className="mt-1 max-w-2xl text-sm leading-6 text-muted-foreground">
                  Generate a protected
                  report from the session
                  data stored by C.L.I.P.
                  Comprehension evidence
                  remains separate from
                  engagement evidence.
                </p>

                <p className="mt-2 text-xs text-muted-foreground">
                  Session ID:{' '}
                  {sessionId ??
                    'Unavailable'}
                </p>
              </div>
            </div>

            {canGenerate && (
              <button
                type="button"
                disabled={
                  !sessionId ||
                  loading
                }
                onClick={() =>
                  void generateReport()
                }
                className="rounded-lg bg-primary px-4 py-2.5 text-sm font-medium text-primary-foreground disabled:cursor-not-allowed disabled:opacity-50"
              >
                {loading
                  ? 'Requesting...'
                  : job?.status ===
                      'failed'
                    ? 'Generate again'
                    : 'Generate report'}
              </button>
            )}
          </div>

          <div className="mt-5 rounded-lg border border-warning/40 bg-warning/10 px-4 py-3 text-sm">
            <p className="font-medium">
              PDF language limitation
            </p>

            <p className="mt-1 text-muted-foreground">
              The current PDF exporter
              uses built-in fonts.
              Non-Latin text, including
              Arabic, may appear as boxes
              in the downloaded PDF. The
              report shown on this page is
              unaffected.
            </p>
          </div>

          {error && (
            <div
              role="alert"
              className="mt-5 rounded-lg border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-destructive"
            >
              {error}
            </div>
          )}

          {job && (
            <div className="mt-6 rounded-xl border border-border bg-background p-5">
              <div className="flex flex-wrap items-center justify-between gap-4">
                <div>
                  <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    Report status
                  </p>

                  <p className="mt-1 text-lg font-semibold">
                    {reportStatusLabel(
                      job.status,
                    )}
                  </p>

                  <p className="mt-1 text-xs text-muted-foreground">
                    Requested:{' '}
                    {dateLabel(
                      job.requested_at,
                    )}
                  </p>
                </div>

                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    disabled={loading}
                    onClick={() =>
                      void refreshReport()
                    }
                    className="inline-flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm font-medium hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <RefreshCw
                      aria-hidden="true"
                      size={15}
                    />

                    {loading
                      ? 'Refreshing...'
                      : 'Refresh'}
                  </button>

                  <button
                    type="button"
                    disabled={
                      !reportIsReady(
                        job,
                      ) ||
                      downloading
                    }
                    onClick={() =>
                      void downloadPdf()
                    }
                    className="inline-flex items-center gap-2 rounded-lg bg-primary px-3 py-2 text-sm font-medium text-primary-foreground disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <Download
                      aria-hidden="true"
                      size={15}
                    />

                    {downloading
                      ? 'Downloading...'
                      : 'Download PDF'}
                  </button>
                </div>
              </div>

              {(
                job.status ===
                  'queued' ||
                job.status ===
                  'running'
              ) && (
                <p
                  role="status"
                  className="mt-4 text-sm text-muted-foreground"
                >
                  The report is being
                  generated. This page
                  checks its status
                  automatically. Temporary
                  refresh failures are
                  retried.
                </p>
              )}

              {failure && (
                <div
                  role="alert"
                  className="mt-4 rounded-lg border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-destructive"
                >
                  {failure}
                </div>
              )}
            </div>
          )}
        </section>

        {report && (
          <>
            <section className="mt-6 rounded-2xl border border-border bg-card p-6 shadow-[var(--shadow-card)]">
              <div>
                <p className="text-sm font-medium text-muted-foreground">
                  {
                    report.course_code
                  }
                </p>

                <h2 className="mt-1 text-2xl font-semibold">
                  {report.title}
                </h2>

                <dl className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                  <div className="rounded-lg border border-border bg-background p-4">
                    <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      Status
                    </dt>

                    <dd className="mt-1 font-semibold capitalize">
                      {
                        report.status
                      }
                    </dd>
                  </div>

                  <div className="rounded-lg border border-border bg-background p-4">
                    <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      Started
                    </dt>

                    <dd className="mt-1 text-sm font-medium">
                      {dateLabel(
                        report.starts_at,
                      )}
                    </dd>
                  </div>

                  <div className="rounded-lg border border-border bg-background p-4">
                    <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      Ended
                    </dt>

                    <dd className="mt-1 text-sm font-medium">
                      {dateLabel(
                        report.ended_at,
                      )}
                    </dd>
                  </div>

                  <div className="rounded-lg border border-border bg-background p-4">
                    <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      Generated
                    </dt>

                    <dd className="mt-1 text-sm font-medium">
                      {dateLabel(
                        report.generated_at,
                      )}
                    </dd>
                  </div>
                </dl>
              </div>
            </section>

            <section className="mt-6 rounded-2xl border border-border bg-card p-6 shadow-[var(--shadow-card)]">
              <h2 className="text-lg font-semibold">
                Participation
              </h2>

              <p className="mt-1 text-sm text-muted-foreground">
                Stored session activity
                only. Missing information
                is not estimated.
              </p>

              <dl className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
                <div className="rounded-lg border border-border bg-background p-4">
                  <dt className="text-xs uppercase tracking-wide text-muted-foreground">
                    Students
                  </dt>

                  <dd className="mt-1 text-2xl font-semibold">
                    {
                      report
                        .participation
                        .students
                    }
                  </dd>
                </div>

                <div className="rounded-lg border border-border bg-background p-4">
                  <dt className="text-xs uppercase tracking-wide text-muted-foreground">
                    Questions
                  </dt>

                  <dd className="mt-1 text-2xl font-semibold">
                    {
                      report
                        .participation
                        .questions_delivered
                    }
                  </dd>
                </div>

                <div className="rounded-lg border border-border bg-background p-4">
                  <dt className="text-xs uppercase tracking-wide text-muted-foreground">
                    Answers
                  </dt>

                  <dd className="mt-1 text-2xl font-semibold">
                    {
                      report
                        .participation
                        .answers
                    }
                  </dd>
                </div>

                <div className="rounded-lg border border-border bg-background p-4">
                  <dt className="text-xs uppercase tracking-wide text-muted-foreground">
                    Missed
                  </dt>

                  <dd className="mt-1 text-2xl font-semibold">
                    {
                      report
                        .participation
                        .missed_answers
                    }
                  </dd>
                </div>

                <div className="rounded-lg border border-border bg-background p-4">
                  <dt className="text-xs uppercase tracking-wide text-muted-foreground">
                    Attention prompts
                  </dt>

                  <dd className="mt-1 text-2xl font-semibold">
                    {
                      report
                        .participation
                        .attention_prompts
                    }
                  </dd>
                </div>
              </dl>
            </section>

            <section className="mt-6 rounded-2xl border border-border bg-card p-6 shadow-[var(--shadow-card)]">
              <h2 className="text-lg font-semibold">
                Topic comprehension
              </h2>

              <p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">
                Topic difficulty comes
                from stored comprehension
                results. It is presented
                separately from
                engagement and attention
                evidence.
              </p>

              {report.topics.length ===
              0 ? (
                <p className="mt-5 rounded-lg border border-border bg-background p-4 text-sm text-muted-foreground">
                  No topic-level
                  comprehension data is
                  available for this
                  report.
                </p>
              ) : (
                <div className="mt-5 space-y-3">
                  {report.topics.map(
                    (topic) => (
                      <article
                        key={
                          topic.topic
                        }
                        className="rounded-xl border border-border bg-background p-4"
                      >
                        <div className="flex flex-wrap items-start justify-between gap-3">
                          <div>
                            <h3 className="font-semibold">
                              {
                                topic.topic
                              }
                            </h3>

                            <p className="mt-1 text-sm text-muted-foreground">
                              {
                                topic.answers
                              }{' '}
                              answers
                              across{' '}
                              {
                                topic.questions
                              }{' '}
                              questions
                            </p>
                          </div>

                          <div className="text-right">
                            <p className="text-sm font-semibold">
                              {topicLevelLabel(
                                topic,
                              )}
                            </p>

                            <p className="mt-1 text-xs text-muted-foreground">
                              Difficulty
                              score:{' '}
                              {topicScoreLabel(
                                topic.score,
                              )}
                            </p>
                          </div>
                        </div>

                        <dl className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
                          <div>
                            <dt className="text-xs text-muted-foreground">
                              Mastered
                            </dt>

                            <dd className="mt-1 font-semibold">
                              {
                                topic.mastered
                              }
                            </dd>
                          </div>

                          <div>
                            <dt className="text-xs text-muted-foreground">
                              Partial
                            </dt>

                            <dd className="mt-1 font-semibold">
                              {
                                topic.partial
                              }
                            </dd>
                          </div>

                          <div>
                            <dt className="text-xs text-muted-foreground">
                              Struggling
                            </dt>

                            <dd className="mt-1 font-semibold">
                              {
                                topic.struggling
                              }
                            </dd>
                          </div>

                          <div>
                            <dt className="text-xs text-muted-foreground">
                              Uncertain
                            </dt>

                            <dd className="mt-1 font-semibold">
                              {
                                topic.uncertain
                              }
                            </dd>
                          </div>
                        </dl>
                      </article>
                    ),
                  )}
                </div>
              )}
            </section>

            <section className="mt-6 rounded-2xl border border-border bg-card p-6 shadow-[var(--shadow-card)]">
              <h2 className="text-lg font-semibold">
                Governance-aware
                alerts
              </h2>

              <p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">
                These are stored session
                alerts and their
                authoritative
                explanations. They are
                not independently
                re-scored by the
                frontend.
              </p>

              {report.alerts.length ===
              0 ? (
                <p className="mt-5 rounded-lg border border-border bg-background p-4 text-sm text-muted-foreground">
                  No stored alerts are
                  included in this
                  report.
                </p>
              ) : (
                <div className="mt-5 space-y-3">
                  {report.alerts.map(
                    (alert) => (
                      <article
                        key={
                          alert.alert_id
                        }
                        className="rounded-xl border border-border bg-background p-4"
                      >
                        <div className="flex flex-wrap items-start justify-between gap-3">
                          <div>
                            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                              {
                                alert.kind
                              }
                            </p>

                            <h3 className="mt-1 font-semibold">
                              {
                                alert.message
                              }
                            </h3>
                          </div>

                          <span className="rounded-full border border-border px-3 py-1 text-xs font-medium">
                            {
                              alert.status
                            }
                          </span>
                        </div>

                        <p className="mt-3 text-sm">
                          {
                            alert.reason
                          }
                        </p>

                        <div className="mt-4 rounded-lg bg-muted/40 p-3">
                          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                            Explanation
                          </p>

                          <p className="mt-1 text-sm">
                            {
                              alert.explanation
                            }
                          </p>
                        </div>

                        <div className="mt-3 rounded-lg bg-muted/40 p-3">
                          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                            Recommendation
                          </p>

                          <p className="mt-1 text-sm">
                            {
                              alert.recommendation
                            }
                          </p>
                        </div>

                        <p className="mt-3 text-xs text-muted-foreground">
                          Raised:{' '}
                          {dateLabel(
                            alert.raised_at,
                          )}
                        </p>
                      </article>
                    ),
                  )}
                </div>
              )}
            </section>
          </>
        )}
      </div>
    </main>
  )
}
