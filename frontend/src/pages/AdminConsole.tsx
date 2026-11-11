import { useRef, useState } from 'react'
import { apiUploadFile, ApiError, type TimetableImportResult } from '../api'
import { signOutToLogin } from '../features/realtime/tokenRefusal'
import { PageBody, PageHeader } from '../components/ui/primitives'

type UploadKind = 'timetable' | 'roster'

interface UploadState {
  status: 'idle' | 'previewing' | 'confirming' | 'success' | 'error'
  result: TimetableImportResult | null
  error: string | null
}

const IDLE_STATE: UploadState = { status: 'idle', result: null, error: null }

const KIND_CONFIG: Record<UploadKind, { title: string; path: string; hint: string }> = {
  timetable: {
    title: 'Timetable',
    path: '/admin/timetable',
    hint: 'CSV or XLSX with course_code, lecturer, day, start_time, end_time, room',
  },
  roster: {
    title: 'Roster',
    path: '/admin/roster',
    hint: 'CSV or XLSX with student_email, student_name, course_code',
  },
}

export default function AdminConsole() {
  return (
    <>
      <PageHeader
        title="Imports"
        description="Preview a week of classes or add students to courses from a spreadsheet."
      />
      <PageBody>
        <div className="grid max-w-3xl gap-6">
          <UploadPanel kind="timetable" />
          <UploadPanel kind="roster" />
        </div>
      </PageBody>
    </>
  )
}

function UploadPanel({ kind }: { kind: UploadKind }) {
  const [state, setState] = useState<UploadState>(IDLE_STATE)
  const [file, setFile] = useState<File | null>(null)
  const [weekStart, setWeekStart] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)
  const inFlight = useRef(false)
  const config = KIND_CONFIG[kind]
  const isBusy = state.status === 'previewing' || state.status === 'confirming'

  function selectFile(nextFile: File) {
    if (inFlight.current) return
    setFile(nextFile)
    setState(IDLE_STATE)
  }

  async function submit(previewToken?: string) {
    if (!file || inFlight.current || (kind === 'timetable' && !weekStart)) return
    inFlight.current = true
    setState({ status: previewToken ? 'confirming' : 'previewing', result: null, error: null })
    const fields: Record<string, string> = {}
    if (kind === 'timetable') fields.week_start = weekStart
    if (previewToken) fields.preview_token = previewToken
    try {
      const result = await apiUploadFile(config.path, file, fields)
      setState({ status: 'success', result, error: null })
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        await signOutToLogin()
        return
      }
      const message = err instanceof ApiError ? err.message : 'Upload failed. Try again.'
      setState({ status: 'error', result: null, error: message })
    } finally {
      inFlight.current = false
    }
  }

  function onInputChange(e: React.ChangeEvent<HTMLInputElement>) {
    const selected = e.target.files?.[0]
    if (selected) selectFile(selected)
    e.target.value = ''
  }

  function onDrop(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault()
    const dropped = e.dataTransfer.files?.[0]
    if (dropped) selectFile(dropped)
  }

  return (
    <section className="rounded-xl border border-border bg-card p-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h2 className="font-semibold text-card-foreground">{config.title}</h2>
          <p className="mt-0.5 text-xs text-muted-foreground">{config.hint}</p>
        </div>
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          disabled={isBusy}
          className="shrink-0 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
        >
          Choose file
        </button>
        <input
          ref={inputRef}
          type="file"
          accept=".csv,.xlsx"
          className="hidden"
          onChange={onInputChange}
        />
      </div>

      <div
        onDragOver={(e) => e.preventDefault()}
        onDrop={onDrop}
        className="mt-4 rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground"
      >
        Drag a .csv or .xlsx file here, or use "Choose file" above.
      </div>

      {kind === 'timetable' && (
        <label className="mt-4 block text-sm font-medium">
          Week starting Monday (Dubai time)
          <input
            type="date"
            className="mt-1 block rounded-lg border border-border bg-background p-2"
            value={weekStart}
            disabled={isBusy}
            onChange={(event) => {
              setWeekStart(event.target.value)
              setState(IDLE_STATE)
            }}
          />
        </label>
      )}
      {file && <p className="mt-3 break-all text-sm text-muted-foreground">{file.name}</p>}
      <div className="mt-4 flex flex-wrap gap-3">
        <button
          type="button"
          disabled={isBusy || !file || (kind === 'timetable' && !weekStart)}
          onClick={() => void submit()}
          className="rounded-lg border border-border px-4 py-2 text-sm font-medium disabled:opacity-50"
        >
          Preview import
        </button>
        {state.result?.preview_token && (
          <button
            type="button"
            onClick={() => void submit(state.result?.preview_token ?? undefined)}
            className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground"
          >
            Confirm import
          </button>
        )}
      </div>
      {isBusy && <p role="status" className="mt-3 text-sm">{state.status === 'confirming' ? 'Saving import…' : 'Checking file…'}</p>}

      {state.status === 'error' && (
        <div role="alert" className="mt-4 rounded-lg bg-critical/10 p-4 text-sm text-critical">
          {state.error}
        </div>
      )}

      {state.status === 'success' && state.result && <ImportResultView result={state.result} />}
    </section>
  )
}

const dubaiTime = new Intl.DateTimeFormat('en-GB', {
  timeZone: 'Asia/Dubai',
  dateStyle: 'medium',
  timeStyle: 'short',
})

function ImportResultView({ result }: { result: TimetableImportResult }) {
  const hasConflicts = result.conflicts.length > 0
  const hasUnmatchedLecturers = result.unmatched_lecturers.length > 0
  const hasUnmatchedStudents = result.unmatched_students.length > 0

  return (
    <div className="mt-4 space-y-4">
      <p role="status" className="text-sm font-medium">
        {result.applied
          ? 'Import saved.'
          : hasConflicts
            ? 'Resolve conflicts to confirm this import.'
            : 'Review these changes before confirming.'}
      </p>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Rows read" value={result.rows_read} />
        <Stat label={result.applied ? 'Courses created' : 'Courses to create'} value={result.courses_changed} />
        <Stat
          label={result.applied ? 'Sessions created' : 'Sessions to create'}
          value={result.applied ? result.sessions_created : result.sessions_to_create}
        />
        <Stat label={result.applied ? 'Memberships added' : 'Memberships to add'} value={result.memberships_changed} />
      </div>
      {!!result.new_course_codes?.length && (
        <IssueList
          title={result.applied ? 'New courses created' : 'This import creates new courses. Check these codes for typos.'}
          tone="warning"
          items={result.new_course_codes}
        />
      )}
      {(hasUnmatchedLecturers || hasUnmatchedStudents) && (
        <p className="rounded-lg bg-warning/10 p-3 text-sm font-medium text-warning">
          {result.applied
            ? 'Rows with unmatched accounts were skipped.'
            : 'Rows with unmatched accounts will be skipped if you confirm.'}
        </p>
      )}
      <details>
        <summary className="cursor-pointer text-sm font-medium">Row details ({result.rows.length})</summary>
        <ul className="mt-2 max-h-80 space-y-2 overflow-auto rounded-lg bg-muted p-3 text-sm">
          {result.rows.map((row) => (
            <li key={row.row}>
              <p className="break-words">Row {row.row} · {row.course_code} · {row.account}</p>
              {row.start_time && row.end_time && (
                <p>{dubaiTime.formatRange(new Date(row.start_time), new Date(row.end_time))} (Dubai) · {row.room}</p>
              )}
              <p className="text-muted-foreground">{row.detail}</p>
            </li>
          ))}
        </ul>
      </details>

      {hasConflicts && (
        <IssueList title="Conflicts" tone="critical" items={result.conflicts} />
      )}

      {hasUnmatchedLecturers && (
        <IssueList
          title="Unmatched lecturers"
          tone="warning"
          items={result.unmatched_lecturers}
        />
      )}

      {hasUnmatchedStudents && (
        <IssueList title="Unmatched students" tone="warning" items={result.unmatched_students} />
      )}
    </div>
  )
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string
  value: number
  tone?: 'critical' | 'warning' | 'success'
}) {
  const toneClass = tone
    ? { critical: 'text-critical', warning: 'text-warning', success: 'text-success' }[tone]
    : 'text-card-foreground'

  return (
    <div className="rounded-lg bg-muted p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={`mt-1 text-lg font-semibold ${toneClass}`}>{value}</p>
    </div>
  )
}

function IssueList({
  title,
  tone,
  items,
}: {
  title: string
  tone: 'critical' | 'warning'
  items: string[]
}) {
  const bg = tone === 'critical' ? 'bg-critical/10' : 'bg-warning/10'
  const text = tone === 'critical' ? 'text-critical' : 'text-warning'

  return (
    <div className={`rounded-lg ${bg} p-3`}>
      <p className={`text-xs font-medium ${text}`}>
        {title} ({items.length})
      </p>
      <ul className="mt-2 space-y-1">
        {items.map((item, i) => (
          <li key={i} className="text-xs text-card-foreground">
            {item}
          </li>
        ))}
      </ul>
    </div>
  )
}
