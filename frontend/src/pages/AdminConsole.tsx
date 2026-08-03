import { useRef, useState } from 'react'
import { apiUploadFile, ApiError, type TimetableImportResult } from '../api'

type UploadKind = 'timetable' | 'roster'

interface UploadState {
  status: 'idle' | 'uploading' | 'success' | 'error'
  result: TimetableImportResult | null
  error: string | null
  filename: string | null
}

const IDLE_STATE: UploadState = { status: 'idle', result: null, error: null, filename: null }

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
    <main className="min-h-screen p-8">
      <div className="mx-auto max-w-3xl">
        <h1 className="text-xl font-bold text-foreground">Administrator console</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Import timetables and student rosters. Only .csv and .xlsx are accepted — every row is
          read as structured data, never guessed at from an image.
        </p>

        <div className="mt-8 space-y-6">
          <UploadPanel kind="timetable" />
          <UploadPanel kind="roster" />
        </div>
      </div>
    </main>
  )
}

function UploadPanel({ kind }: { kind: UploadKind }) {
  const [state, setState] = useState<UploadState>(IDLE_STATE)
  const inputRef = useRef<HTMLInputElement>(null)
  const config = KIND_CONFIG[kind]

  async function handleFile(file: File) {
    setState({ status: 'uploading', result: null, error: null, filename: file.name })
    try {
      const result = await apiUploadFile(config.path, file)
      setState({ status: 'success', result, error: null, filename: file.name })
    } catch (err) {
      const message = err instanceof ApiError ? err.message : 'Upload failed. Try again.'
      setState({ status: 'error', result: null, error: message, filename: file.name })
    }
  }

  function onInputChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (file) void handleFile(file)
    e.target.value = '' // allow re-selecting the same file after a failed upload
  }

  function onDrop(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault()
    const file = e.dataTransfer.files?.[0]
    if (file) void handleFile(file)
  }

  const isBusy = state.status === 'uploading'

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
          {isBusy ? 'Uploading…' : 'Choose file'}
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

      {state.filename && (
        <p className="mt-3 text-xs text-muted-foreground">
          {state.status === 'uploading' ? 'Uploading' : 'Last file'}: {state.filename}
        </p>
      )}

      {state.status === 'error' && (
        <div className="mt-4 rounded-lg bg-critical/10 p-4 text-sm text-critical">
          {state.error}
        </div>
      )}

      {state.status === 'success' && state.result && <ImportResultView result={state.result} />}
    </section>
  )
}

function ImportResultView({ result }: { result: TimetableImportResult }) {
  const hasConflicts = result.conflicts.length > 0
  const hasUnmatchedLecturers = result.unmatched_lecturers.length > 0
  const hasUnmatchedStudents = result.unmatched_students.length > 0
  const hasIssues = hasConflicts || hasUnmatchedLecturers || hasUnmatchedStudents

  return (
    <div className="mt-4 space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Rows read" value={result.rows_read} />
        <Stat label="Sessions created" value={result.sessions_created} />
        <Stat
          label="Conflicts"
          value={result.conflicts.length}
          tone={hasConflicts ? 'critical' : 'success'}
        />
        <Stat
          label="Unmatched"
          value={result.unmatched_lecturers.length + result.unmatched_students.length}
          tone={hasUnmatchedLecturers || hasUnmatchedStudents ? 'warning' : 'success'}
        />
      </div>

      {!hasIssues && (
        <p className="rounded-lg bg-success/10 p-3 text-sm text-success">
          No conflicts and every name matched.
        </p>
      )}

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
