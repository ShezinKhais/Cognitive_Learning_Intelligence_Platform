import {
  useEffect,
  useState,
  type FormEvent,
} from 'react'
import {
  FileClock,
  RefreshCw,
  ShieldCheck,
  Trash2,
} from 'lucide-react'
import { Link } from 'react-router'

import {
  ApiError,
  clearAccessToken,
  getCurrentUser,
} from '../api'
import SignOutButton from '../components/SignOutButton'
import {
  canApproveDeletion,
  canExecuteDeletion,
  canRejectDeletion,
  deletionStatusLabel,
  deletionTargetLabel,
  isValidUuid,
  type AuditEntry,
  type DeletionRequest,
  type DeletionRequestStatus,
  type DeletionTargetType,
  type RetentionReport,
} from '../features/governance/governance'
import {
  approveDeletionRequest,
  createDeletionRequest,
  executeDeletionRequest,
  listAuditLog,
  listDeletionRequests,
  previewRetention,
  rejectDeletionRequest,
  runRetention,
} from '../features/governance/governanceApi'

const AUDIT_PAGE_SIZE = 50
const DELETION_PAGE_SIZE = 50

function dateLabel(
  value: string | null,
): string {
  if (!value) {
    return 'Unavailable'
  }

  const parsed = Date.parse(value)

  if (Number.isNaN(parsed)) {
    return 'Unavailable'
  }

  return new Date(
    parsed,
  ).toLocaleString()
}

function detailsLabel(
  details:
    Record<string, unknown> | null,
): string {
  if (!details) {
    return 'No additional metadata'
  }

  const entries =
    Object.entries(details)

  if (entries.length === 0) {
    return 'No additional metadata'
  }

  return entries
    .map(
      ([key, value]) =>
        `${key}: ${
          typeof value === 'object' &&
          value !== null
            ? JSON.stringify(value)
            : String(value)
        }`,
    )
    .join(' · ')
}

export default function AdminGovernancePage() {
  const [
    adminId,
    setAdminId,
  ] = useState('')

  const [
    identityLoading,
    setIdentityLoading,
  ] = useState(true)

  const [
    auditEntries,
    setAuditEntries,
  ] =
    useState<AuditEntry[]>([])

  const [
    auditTotal,
    setAuditTotal,
  ] = useState(0)

  const [
    auditOffset,
    setAuditOffset,
  ] = useState(0)

  const [
    auditLoading,
    setAuditLoading,
  ] = useState(false)

  const [
    auditError,
    setAuditError,
  ] =
    useState<string | null>(
      null,
    )

  const [
    auditActionFilter,
    setAuditActionFilter,
  ] = useState('')

  const [
    auditTargetFilter,
    setAuditTargetFilter,
  ] = useState('')

  const [
    appliedAuditActionFilter,
    setAppliedAuditActionFilter,
  ] = useState('')

  const [
    appliedAuditTargetFilter,
    setAppliedAuditTargetFilter,
  ] = useState('')

  const [
    deletionRequests,
    setDeletionRequests,
  ] =
    useState<DeletionRequest[]>([])

  const [
    deletionTotal,
    setDeletionTotal,
  ] = useState(0)

  const [
    deletionOffset,
    setDeletionOffset,
  ] = useState(0)

  const [
    deletionLoading,
    setDeletionLoading,
  ] = useState(false)

  const [
    deletionError,
    setDeletionError,
  ] =
    useState<string | null>(
      null,
    )

  const [
    deletionStatusFilter,
    setDeletionStatusFilter,
  ] =
    useState<
      DeletionRequestStatus | ''
    >('')

  const [
    appliedDeletionStatusFilter,
    setAppliedDeletionStatusFilter,
  ] =
    useState<
      DeletionRequestStatus | ''
    >('')

  const [
    retention,
    setRetention,
  ] =
    useState<RetentionReport | null>(
      null,
    )

  const [
    retentionLoading,
    setRetentionLoading,
  ] = useState(false)

  const [
    retentionError,
    setRetentionError,
  ] =
    useState<string | null>(
      null,
    )

  const [
    busyAction,
    setBusyAction,
  ] =
    useState<string | null>(
      null,
    )

  const [
    error,
    setError,
  ] =
    useState<string | null>(
      null,
    )

  const [
    notice,
    setNotice,
  ] =
    useState<string | null>(
      null,
    )

  const [
    targetType,
    setTargetType,
  ] =
    useState<DeletionTargetType>(
      'session',
    )

  const [
    targetId,
    setTargetId,
  ] = useState('')

  const [
    reason,
    setReason,
  ] = useState('')

  const [
    confirmPurge,
    setConfirmPurge,
  ] = useState(false)

  const [
    pendingExecutionId,
    setPendingExecutionId,
  ] =
    useState<string | null>(
      null,
    )

  const [
    confirmDeletion,
    setConfirmDeletion,
  ] = useState(false)

  function apiErrorMessage(
    caught: unknown,
    fallback: string,
  ): string | null {
    if (
      caught instanceof ApiError &&
      caught.status === 401
    ) {
      clearAccessToken()

      window.location.assign(
        '/login',
      )

      return null
    }

    return caught instanceof ApiError
      ? caught.message
      : fallback
  }

  async function loadAudit(
    nextOffset = auditOffset,
    actionFilter =
      appliedAuditActionFilter,
    targetFilter =
      appliedAuditTargetFilter,
  ) {
    setAuditLoading(true)
    setAuditError(null)

    try {
      const result =
        await listAuditLog(
          {
            action_type:
              actionFilter ||
              undefined,
            target_type:
              targetFilter ||
              undefined,
          },
          AUDIT_PAGE_SIZE,
          nextOffset,
        )

      setAuditEntries(
        result.items,
      )

      setAuditTotal(
        result.total,
      )

      setAuditOffset(
        nextOffset,
      )
    } catch (
      caught: unknown
    ) {
      const message =
        apiErrorMessage(
          caught,
          'The audit log could not be loaded.',
        )

      if (message) {
        setAuditError(
          message,
        )
      }
    } finally {
      setAuditLoading(false)
    }
  }

  async function applyAuditFilters() {
    const actionFilter =
      auditActionFilter.trim()

    const targetFilter =
      auditTargetFilter.trim()

    setAppliedAuditActionFilter(
      actionFilter,
    )

    setAppliedAuditTargetFilter(
      targetFilter,
    )

    await loadAudit(
      0,
      actionFilter,
      targetFilter,
    )
  }

  async function loadDeletionRequests(
    nextOffset = deletionOffset,
    status =
      appliedDeletionStatusFilter,
  ) {
    setDeletionLoading(true)
    setDeletionError(null)

    try {
      const result =
        await listDeletionRequests(
          status || undefined,
          DELETION_PAGE_SIZE,
          nextOffset,
        )

      setDeletionRequests(
        result.items,
      )

      setDeletionTotal(
        result.total,
      )

      setDeletionOffset(
        nextOffset,
      )
    } catch (
      caught: unknown
    ) {
      const message =
        apiErrorMessage(
          caught,
          'Deletion requests could not be loaded.',
        )

      if (message) {
        setDeletionError(
          message,
        )
      }
    } finally {
      setDeletionLoading(false)
    }
  }

  async function applyDeletionFilter() {
    const status =
      deletionStatusFilter

    setAppliedDeletionStatusFilter(
      status,
    )

    await loadDeletionRequests(
      0,
      status,
    )
  }

  async function loadRetention() {
    setRetentionLoading(true)
    setRetentionError(null)

    try {
      const result =
        await previewRetention()

      setRetention(result)
    } catch (
      caught: unknown
    ) {
      const message =
        apiErrorMessage(
          caught,
          'The retention preview could not be loaded.',
        )

      if (message) {
        setRetentionError(
          message,
        )
      }
    } finally {
      setRetentionLoading(false)
    }
  }

  useEffect(() => {
    let active = true

    function handleInitialError(
      caught: unknown,
      fallback: string,
      setSectionError:
        (
          value: string | null,
        ) => void,
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

      setSectionError(
        caught instanceof ApiError
          ? caught.message
          : fallback,
      )
    }

    async function loadIdentity() {
      setIdentityLoading(true)
      setError(null)

      try {
        const user =
          await getCurrentUser()

        if (!active) {
          return
        }

        setAdminId(user.id)
      } catch (
        caught: unknown
      ) {
        handleInitialError(
          caught,
          'Your administrator identity could not be loaded.',
          setError,
        )
      } finally {
        if (active) {
          setIdentityLoading(
            false,
          )
        }
      }
    }

    async function loadInitialAudit() {
      setAuditLoading(true)
      setAuditError(null)

      try {
        const result =
          await listAuditLog(
            {},
            AUDIT_PAGE_SIZE,
            0,
          )

        if (!active) {
          return
        }

        setAuditEntries(
          result.items,
        )

        setAuditTotal(
          result.total,
        )

        setAuditOffset(0)
      } catch (
        caught: unknown
      ) {
        handleInitialError(
          caught,
          'The audit log could not be loaded.',
          setAuditError,
        )
      } finally {
        if (active) {
          setAuditLoading(
            false,
          )
        }
      }
    }

    async function loadInitialDeletionRequests() {
      setDeletionLoading(true)
      setDeletionError(null)

      try {
        const result =
          await listDeletionRequests(
            undefined,
            DELETION_PAGE_SIZE,
            0,
          )

        if (!active) {
          return
        }

        setDeletionRequests(
          result.items,
        )

        setDeletionTotal(
          result.total,
        )

        setDeletionOffset(0)
      } catch (
        caught: unknown
      ) {
        handleInitialError(
          caught,
          'Deletion requests could not be loaded.',
          setDeletionError,
        )
      } finally {
        if (active) {
          setDeletionLoading(
            false,
          )
        }
      }
    }

    async function loadInitialRetention() {
      setRetentionLoading(true)
      setRetentionError(null)

      try {
        const result =
          await previewRetention()

        if (!active) {
          return
        }

        setRetention(result)
      } catch (
        caught: unknown
      ) {
        handleInitialError(
          caught,
          'The retention preview could not be loaded.',
          setRetentionError,
        )
      } finally {
        if (active) {
          setRetentionLoading(
            false,
          )
        }
      }
    }

    void loadIdentity()
    void loadInitialAudit()
    void loadInitialDeletionRequests()
    void loadInitialRetention()

    return () => {
      active = false
    }
  }, [])

  async function handleCreateDeletion(
    event:
      FormEvent<HTMLFormElement>,
  ) {
    event.preventDefault()

    const cleanTargetId =
      targetId.trim()

    if (!cleanTargetId) {
      setError(
        'Enter the target ID.',
      )

      return
    }

    if (
      !isValidUuid(
        cleanTargetId,
      )
    ) {
      setError(
        'Enter a valid UUID for the deletion target.',
      )

      return
    }

    setBusyAction(
      'create-deletion',
    )

    setError(null)
    setNotice(null)

    try {
      await createDeletionRequest({
        target_type:
          targetType,
        target_id:
          cleanTargetId,
        reason:
          reason.trim() ||
          null,
      })

      setTargetId('')
      setReason('')

      setNotice(
        'Deletion request created. A different administrator must approve it before execution.',
      )

      await Promise.all([
        loadDeletionRequests(0),
        loadAudit(0),
      ])
    } catch (
      caught: unknown
    ) {
      const message =
        apiErrorMessage(
          caught,
          'The deletion request could not be created.',
        )

      if (message) {
        setError(message)
      }
    } finally {
      setBusyAction(null)
    }
  }

  async function handleDeletionAction(
    request:
      DeletionRequest,
    action:
      | 'approve'
      | 'reject'
      | 'execute',
  ) {
    const key =
      `${action}-${request.request_id}`

    setBusyAction(key)
    setError(null)
    setNotice(null)

    try {
      if (action === 'approve') {
        await approveDeletionRequest(
          request.request_id,
        )

        setNotice(
          'Deletion request approved.',
        )
      } else if (
        action === 'reject'
      ) {
        await rejectDeletionRequest(
          request.request_id,
        )

        setNotice(
          'Deletion request rejected.',
        )
      } else {
        await executeDeletionRequest(
          request.request_id,
        )

        setPendingExecutionId(
          null,
        )

        setConfirmDeletion(
          false,
        )

        setNotice(
          'Approved session deletion executed.',
        )
      }

      await Promise.all([
        loadDeletionRequests(),
        loadAudit(0),
        loadRetention(),
      ])
    } catch (
      caught: unknown
    ) {
      const actionLabel =
        action === 'approve'
          ? 'approved'
          : action === 'reject'
            ? 'rejected'
            : 'executed'

      const message =
        apiErrorMessage(
          caught,
          `The deletion request could not be ${actionLabel}.`,
        )

      if (message) {
        setError(message)
      }
    } finally {
      setBusyAction(null)
    }
  }

  function requestDeletionExecution(
    request: DeletionRequest,
  ) {
    setPendingExecutionId(
      request.request_id,
    )

    setConfirmDeletion(
      false,
    )

    setError(null)
    setNotice(null)
  }

  function cancelDeletionExecution() {
    setPendingExecutionId(
      null,
    )

    setConfirmDeletion(
      false,
    )
  }

  async function handleRetentionRun() {
    if (!confirmPurge) {
      return
    }

    setBusyAction(
      'retention-run',
    )

    setError(null)
    setNotice(null)

    try {
      const result =
        await runRetention()

      setRetention(result)

      setNotice(
        `Retention purge completed. ${result.sessions} sessions, ${result.answers} answers and ${result.roster_syncs} roster syncs were removed.`,
      )

      setConfirmPurge(false)

      await Promise.all([
        loadAudit(0),
        loadDeletionRequests(),
      ])
    } catch (
      caught: unknown
    ) {
      const message =
        apiErrorMessage(
          caught,
          'The retention purge could not be completed.',
        )

      if (message) {
        setError(message)
      }
    } finally {
      setBusyAction(null)
    }
  }

  const auditFirst =
    auditTotal === 0
      ? 0
      : auditOffset + 1

  const auditLast =
    Math.min(
      auditOffset +
        auditEntries.length,
      auditTotal,
    )

  const hasPreviousAuditPage =
    auditOffset > 0

  const hasNextAuditPage =
    auditOffset +
      AUDIT_PAGE_SIZE <
    auditTotal

  const deletionFirst =
    deletionTotal === 0
      ? 0
      : deletionOffset + 1

  const deletionLast =
    Math.min(
      deletionOffset +
        deletionRequests.length,
      deletionTotal,
    )

  const hasPreviousDeletionPage =
    deletionOffset > 0

  const hasNextDeletionPage =
    deletionOffset +
      DELETION_PAGE_SIZE <
    deletionTotal

  const retentionHeading =
    retention
      ? `${retention.retention_days}-day retention`
      : 'Configured retention'

  if (identityLoading) {
    return (
      <main className="min-h-screen bg-background p-8">
        <p
          role="status"
          className="text-sm text-muted-foreground"
        >
          Loading governance controls...
        </p>
      </main>
    )
  }

  return (
    <main className="min-h-screen bg-background">
      <header className="border-b border-border bg-card">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-5 py-4 sm:px-8">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
              C.L.I.P administration
            </p>

            <h1 className="mt-1 text-xl font-bold text-card-foreground">
              Governance
            </h1>
          </div>

          <div className="flex items-center gap-3">
            <Link
              to="/admin"
              className="rounded-lg border border-border px-3 py-2 text-sm font-medium hover:bg-muted"
            >
              Admin console
            </Link>

            <SignOutButton />
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-7xl px-5 py-8 sm:px-8">
        <div className="flex items-start gap-3">
          <div className="grid size-11 shrink-0 place-items-center rounded-xl bg-info/10 text-info">
            <ShieldCheck
              aria-hidden="true"
              size={22}
            />
          </div>

          <div>
            <h2 className="text-2xl font-semibold">
              Governance controls
            </h2>

            <p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">
              Review metadata-only audit
              events, retention activity
              and authorised deletion
              requests. These controls
              do not display raw student
              content.
            </p>
          </div>
        </div>

        {error && (
          <div
            role="alert"
            className="mt-6 rounded-lg border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-destructive"
          >
            {error}
          </div>
        )}

        {notice && (
          <div
            role="status"
            className="mt-6 rounded-lg border border-border bg-muted/30 px-4 py-3 text-sm"
          >
            {notice}
          </div>
        )}

        <section className="mt-8 rounded-2xl border border-border bg-card p-6">
          <div className="flex items-start gap-3">
            <FileClock
              aria-hidden="true"
              size={20}
              className="mt-0.5"
            />

            <div>
              <h2 className="text-lg font-semibold">
                {retentionHeading}
              </h2>

              <p className="mt-1 text-sm text-muted-foreground">
                Preview data that is
                beyond the configured
                retention period before
                permanently purging it.
              </p>
            </div>
          </div>

          {retentionError && (
            <div
              role="alert"
              className="mt-4 rounded-lg border border-warning/40 bg-warning/10 px-4 py-3 text-sm"
            >
              {retentionError}
            </div>
          )}

          {retentionLoading && (
            <p
              role="status"
              className="mt-4 text-sm text-muted-foreground"
            >
              Loading retention preview...
            </p>
          )}

          {retention && (
            <>
              <dl className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <div className="rounded-lg border border-border bg-background p-4">
                  <dt className="text-xs uppercase tracking-wide text-muted-foreground">
                    Retention period
                  </dt>

                  <dd className="mt-1 text-xl font-semibold">
                    {
                      retention.retention_days
                    }{' '}
                    days
                  </dd>
                </div>

                <div className="rounded-lg border border-border bg-background p-4">
                  <dt className="text-xs uppercase tracking-wide text-muted-foreground">
                    Sessions
                  </dt>

                  <dd className="mt-1 text-xl font-semibold">
                    {
                      retention.sessions
                    }
                  </dd>
                </div>

                <div className="rounded-lg border border-border bg-background p-4">
                  <dt className="text-xs uppercase tracking-wide text-muted-foreground">
                    Answers
                  </dt>

                  <dd className="mt-1 text-xl font-semibold">
                    {
                      retention.answers
                    }
                  </dd>
                </div>

                <div className="rounded-lg border border-border bg-background p-4">
                  <dt className="text-xs uppercase tracking-wide text-muted-foreground">
                    Roster syncs
                  </dt>

                  <dd className="mt-1 text-xl font-semibold">
                    {
                      retention.roster_syncs
                    }
                  </dd>
                </div>
              </dl>

              <p className="mt-4 text-xs text-muted-foreground">
                Cutoff:{' '}
                {dateLabel(
                  retention.cutoff,
                )}
              </p>
            </>
          )}

          <div className="mt-5 flex flex-wrap items-center gap-4">
            <button
              type="button"
              disabled={
                busyAction !== null ||
                retentionLoading
              }
              onClick={() =>
                void loadRetention()
              }
              className="inline-flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm font-medium hover:bg-muted disabled:opacity-50"
            >
              <RefreshCw
                aria-hidden="true"
                size={15}
              />

              Refresh preview
            </button>

            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={
                  confirmPurge
                }
                onChange={(event) =>
                  setConfirmPurge(
                    event.target
                      .checked,
                  )
                }
              />

              I understand the purge
              cannot be undone
            </label>

            <button
              type="button"
              disabled={
                !confirmPurge ||
                busyAction !== null ||
                retentionLoading
              }
              onClick={() =>
                void handleRetentionRun()
              }
              className="rounded-lg bg-destructive px-4 py-2 text-sm font-medium text-destructive-foreground disabled:cursor-not-allowed disabled:opacity-50"
            >
              {busyAction ===
              'retention-run'
                ? 'Purging...'
                : 'Run retention purge'}
            </button>
          </div>
        </section>

        <section className="mt-6 rounded-2xl border border-border bg-card p-6">
          <div className="flex items-start gap-3">
            <Trash2
              aria-hidden="true"
              size={20}
              className="mt-0.5"
            />

            <div>
              <h2 className="text-lg font-semibold">
                Deletion requests
              </h2>

              <p className="mt-1 text-sm text-muted-foreground">
                A different administrator
                must approve a request
                before a session deletion
                can be executed.
              </p>
            </div>
          </div>

          {deletionError && (
            <div
              role="alert"
              className="mt-4 rounded-lg border border-warning/40 bg-warning/10 px-4 py-3 text-sm"
            >
              {deletionError}
            </div>
          )}

          <form
            className="mt-5 grid gap-4 lg:grid-cols-[160px_1fr_1fr_auto]"
            onSubmit={
              handleCreateDeletion
            }
          >
            <div>
              <label
                htmlFor="deletion-target-type"
                className="text-sm font-medium"
              >
                Target type
              </label>

              <select
                id="deletion-target-type"
                value={targetType}
                onChange={(event) =>
                  setTargetType(
                    event.target
                      .value as DeletionTargetType,
                  )
                }
                className="mt-2 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm"
              >
                <option value="session">
                  Session
                </option>

                <option value="student">
                  Student
                </option>
              </select>
            </div>

            <div>
              <label
                htmlFor="deletion-target-id"
                className="text-sm font-medium"
              >
                Target ID
              </label>

              <input
                id="deletion-target-id"
                value={targetId}
                onChange={(event) =>
                  setTargetId(
                    event.target.value,
                  )
                }
                className="mt-2 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm"
                placeholder="UUID"
              />
            </div>

            <div>
              <label
                htmlFor="deletion-reason"
                className="text-sm font-medium"
              >
                Reason
              </label>

              <input
                id="deletion-reason"
                value={reason}
                maxLength={500}
                onChange={(event) =>
                  setReason(
                    event.target.value,
                  )
                }
                className="mt-2 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm"
                placeholder="Optional short reason"
              />
            </div>

            <button
              type="submit"
              disabled={
                busyAction !== null
              }
              className="self-end rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
            >
              Request deletion
            </button>
          </form>

          {targetType ===
            'student' && (
            <p className="mt-3 text-xs text-muted-foreground">
              Student deletion
              requests may be reviewed,
              but individual-student
              erasure is not yet
              executable by the current
              backend contract.
            </p>
          )}

          <div className="mt-6 flex flex-wrap items-end justify-between gap-4">
            <div>
              <label
                htmlFor="deletion-status-filter"
                className="text-sm font-medium"
              >
                Status filter
              </label>

              <select
                id="deletion-status-filter"
                value={
                  deletionStatusFilter
                }
                onChange={(event) =>
                  setDeletionStatusFilter(
                    event.target
                      .value as
                      | DeletionRequestStatus
                      | '',
                  )
                }
                className="mt-2 block rounded-lg border border-border bg-background px-3 py-2 text-sm"
              >
                <option value="">
                  All
                </option>

                <option value="requested">
                  Requested
                </option>

                <option value="approved">
                  Approved
                </option>

                <option value="rejected">
                  Rejected
                </option>

                <option value="executed">
                  Executed
                </option>
              </select>
            </div>

            <button
              type="button"
              onClick={() =>
                void applyDeletionFilter()
              }
              disabled={
                busyAction !== null ||
                deletionLoading
              }
              className="rounded-lg border border-border px-3 py-2 text-sm font-medium hover:bg-muted disabled:opacity-50"
            >
              {deletionLoading
                ? 'Loading...'
                : 'Apply filter'}
            </button>
          </div>

          <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
            <p className="text-xs text-muted-foreground">
              Showing{' '}
              {deletionFirst}
              {deletionTotal > 0
                ? `–${deletionLast}`
                : ''}{' '}
              of {deletionTotal} requests
            </p>

            <div className="flex gap-2">
              <button
                type="button"
                disabled={
                  !hasPreviousDeletionPage ||
                  deletionLoading ||
                  busyAction !== null
                }
                onClick={() =>
                  void loadDeletionRequests(
                    Math.max(
                      0,
                      deletionOffset -
                        DELETION_PAGE_SIZE,
                    ),
                  )
                }
                className="rounded-lg border border-border px-3 py-2 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50"
              >
                Previous
              </button>

              <button
                type="button"
                disabled={
                  !hasNextDeletionPage ||
                  deletionLoading ||
                  busyAction !== null
                }
                onClick={() =>
                  void loadDeletionRequests(
                    deletionOffset +
                      DELETION_PAGE_SIZE,
                  )
                }
                className="rounded-lg border border-border px-3 py-2 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50"
              >
                Next
              </button>
            </div>
          </div>

          <div className="mt-5 space-y-3">
            {deletionLoading &&
              deletionRequests.length ===
                0 && (
                <p
                  role="status"
                  className="rounded-lg border border-border bg-background p-4 text-sm text-muted-foreground"
                >
                  Loading deletion
                  requests...
                </p>
              )}

            {!deletionLoading &&
            deletionRequests.length ===
              0 ? (
              <p className="rounded-lg border border-border bg-background p-4 text-sm text-muted-foreground">
                No deletion requests
                found.
              </p>
            ) : (
              deletionRequests.map(
                (request) => (
                  <article
                    key={
                      request.request_id
                    }
                    className="rounded-xl border border-border bg-background p-4"
                  >
                    <div className="flex flex-wrap items-start justify-between gap-4">
                      <div>
                        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                          {deletionTargetLabel(
                            request.target_type,
                          )}
                        </p>

                        <p className="mt-1 break-all font-mono text-sm">
                          {
                            request.target_id
                          }
                        </p>

                        <p className="mt-2 text-xs text-muted-foreground">
                          Requested:{' '}
                          {dateLabel(
                            request.requested_at,
                          )}
                        </p>

                        {request.reason && (
                          <p className="mt-2 text-sm">
                            {
                              request.reason
                            }
                          </p>
                        )}
                      </div>

                      <span className="rounded-full border border-border px-3 py-1 text-xs font-semibold">
                        {deletionStatusLabel(
                          request.status,
                        )}
                      </span>
                    </div>

                    <div className="mt-4 flex flex-wrap gap-2">
                      <button
                        type="button"
                        disabled={
                          !adminId ||
                          !canApproveDeletion(
                            request,
                            adminId,
                          ) ||
                          busyAction !==
                            null
                        }
                        onClick={() =>
                          void handleDeletionAction(
                            request,
                            'approve',
                          )
                        }
                        className="rounded-lg border border-border px-3 py-2 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        Approve
                      </button>

                      <button
                        type="button"
                        disabled={
                          !canRejectDeletion(
                            request,
                          ) ||
                          busyAction !==
                            null
                        }
                        onClick={() =>
                          void handleDeletionAction(
                            request,
                            'reject',
                          )
                        }
                        className="rounded-lg border border-border px-3 py-2 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        Reject
                      </button>

                      <button
                        type="button"
                        disabled={
                          !canExecuteDeletion(
                            request,
                          ) ||
                          busyAction !==
                            null
                        }
                        onClick={() =>
                          requestDeletionExecution(
                            request,
                          )
                        }
                        className="rounded-lg bg-destructive px-3 py-2 text-sm font-medium text-destructive-foreground disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        Execute deletion
                      </button>
                    </div>

                    {pendingExecutionId ===
                      request.request_id && (
                      <div
                        role="group"
                        aria-label="Confirm irreversible session deletion"
                        className="mt-4 rounded-lg border border-destructive/40 bg-destructive/10 p-4"
                      >
                        <p className="text-sm font-semibold">
                          Confirm permanent
                          session deletion
                        </p>

                        <p className="mt-1 text-sm text-muted-foreground">
                          This operation
                          permanently deletes
                          the data covered by
                          this approved request
                          and cannot be undone.
                        </p>

                        <label className="mt-3 flex items-start gap-2 text-sm">
                          <input
                            type="checkbox"
                            checked={
                              confirmDeletion
                            }
                            onChange={(
                              event,
                            ) =>
                              setConfirmDeletion(
                                event
                                  .target
                                  .checked,
                              )
                            }
                          />

                          <span>
                            I understand this
                            deletion is
                            irreversible.
                          </span>
                        </label>

                        <div className="mt-4 flex flex-wrap gap-2">
                          <button
                            type="button"
                            disabled={
                              !confirmDeletion ||
                              busyAction !==
                                null
                            }
                            onClick={() =>
                              void handleDeletionAction(
                                request,
                                'execute',
                              )
                            }
                            className="rounded-lg bg-destructive px-3 py-2 text-sm font-medium text-destructive-foreground disabled:cursor-not-allowed disabled:opacity-50"
                          >
                            {busyAction ===
                            `execute-${request.request_id}`
                              ? 'Deleting...'
                              : 'Confirm deletion'}
                          </button>

                          <button
                            type="button"
                            disabled={
                              busyAction !==
                              null
                            }
                            onClick={
                              cancelDeletionExecution
                            }
                            className="rounded-lg border border-border px-3 py-2 text-sm font-medium disabled:opacity-50"
                          >
                            Cancel
                          </button>
                        </div>
                      </div>
                    )}

                    {request.status ===
                      'approved' &&
                      request.target_type ===
                        'student' && (
                        <p className="mt-3 text-xs text-muted-foreground">
                          Student erasure
                          execution is not
                          available in the
                          current backend.
                        </p>
                      )}
                  </article>
                ),
              )
            )}
          </div>
        </section>

        <section className="mt-6 rounded-2xl border border-border bg-card p-6">
          <h2 className="text-lg font-semibold">
            Audit log
          </h2>

          <p className="mt-1 text-sm text-muted-foreground">
            Governance metadata only.
            Newest events appear first.
          </p>

          {auditError && (
            <div
              role="alert"
              className="mt-4 rounded-lg border border-warning/40 bg-warning/10 px-4 py-3 text-sm"
            >
              {auditError}
            </div>
          )}

          <div className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-[1fr_1fr_auto]">
            <div>
              <label
                htmlFor="audit-action"
                className="text-sm font-medium"
              >
                Action type
              </label>

              <input
                id="audit-action"
                value={
                  auditActionFilter
                }
                onChange={(event) =>
                  setAuditActionFilter(
                    event.target.value,
                  )
                }
                placeholder="Example: RETENTION_PURGE"
                className="mt-2 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm"
              />
            </div>

            <div>
              <label
                htmlFor="audit-target"
                className="text-sm font-medium"
              >
                Target type
              </label>

              <input
                id="audit-target"
                value={
                  auditTargetFilter
                }
                onChange={(event) =>
                  setAuditTargetFilter(
                    event.target.value,
                  )
                }
                placeholder="Example: session"
                className="mt-2 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm"
              />
            </div>

            <button
              type="button"
              disabled={
                auditLoading
              }
              onClick={() =>
                void applyAuditFilters()
              }
              className="self-end rounded-lg border border-border px-3 py-2 text-sm font-medium hover:bg-muted disabled:opacity-50"
            >
              {auditLoading
                ? 'Loading...'
                : 'Apply filters'}
            </button>
          </div>

          <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
            <p className="text-xs text-muted-foreground">
              Showing{' '}
              {auditFirst}
              {auditTotal > 0
                ? `–${auditLast}`
                : ''}{' '}
              of {auditTotal} events
            </p>

            <div className="flex gap-2">
              <button
                type="button"
                disabled={
                  !hasPreviousAuditPage ||
                  auditLoading
                }
                onClick={() =>
                  void loadAudit(
                    Math.max(
                      0,
                      auditOffset -
                        AUDIT_PAGE_SIZE,
                    ),
                  )
                }
                className="rounded-lg border border-border px-3 py-2 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50"
              >
                Previous
              </button>

              <button
                type="button"
                disabled={
                  !hasNextAuditPage ||
                  auditLoading
                }
                onClick={() =>
                  void loadAudit(
                    auditOffset +
                      AUDIT_PAGE_SIZE,
                  )
                }
                className="rounded-lg border border-border px-3 py-2 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50"
              >
                Next
              </button>
            </div>
          </div>

          <div className="mt-4 space-y-3">
            {auditLoading &&
              auditEntries.length ===
                0 && (
                <p
                  role="status"
                  className="rounded-lg border border-border bg-background p-4 text-sm text-muted-foreground"
                >
                  Loading audit
                  events...
                </p>
              )}

            {!auditLoading &&
            auditEntries.length ===
              0 ? (
              <p className="rounded-lg border border-border bg-background p-4 text-sm text-muted-foreground">
                No audit events match
                these filters.
              </p>
            ) : (
              auditEntries.map(
                (entry) => (
                  <article
                    key={entry.log_id}
                    className="rounded-xl border border-border bg-background p-4"
                  >
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <h3 className="font-semibold">
                          {
                            entry.action_type
                          }
                        </h3>

                        <p className="mt-1 text-xs text-muted-foreground">
                          {dateLabel(
                            entry.timestamp,
                          )}
                        </p>
                      </div>

                      {entry.target_type && (
                        <span className="rounded-full border border-border px-3 py-1 text-xs">
                          {
                            entry.target_type
                          }
                        </span>
                      )}
                    </div>

                    {entry.target_id && (
                      <p className="mt-3 break-all font-mono text-xs">
                        Target:{' '}
                        {
                          entry.target_id
                        }
                      </p>
                    )}

                    <div className="mt-3 grid gap-2 text-xs text-muted-foreground sm:grid-cols-2">
                      <p>
                        Actor:{' '}
                        <span className="break-all font-mono text-foreground">
                          {entry.user_id ??
                            'System'}
                        </span>
                      </p>

                      <p>
                        IP address:{' '}
                        <span className="break-all font-mono text-foreground">
                          {entry.ip_address ??
                            'Unavailable'}
                        </span>
                      </p>
                    </div>

                    <p className="mt-3 text-xs text-muted-foreground">
                      {detailsLabel(
                        entry.details,
                      )}
                    </p>
                  </article>
                ),
              )
            )}
          </div>
        </section>
      </div>
    </main>
  )
}