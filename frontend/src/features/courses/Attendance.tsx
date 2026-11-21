import { useEffect, useState } from 'react'
import { Download } from 'lucide-react'

import { ApiError, apiAuthenticatedGet, authenticatedFetch } from '../../api'
import { buttonStyles } from '../../components/ui/button'
import { Panel, Tag } from '../../components/ui/primitives'

interface CourseAttendance {
  course_code: string
  classes: { session_id: string; title: string; starts_at: string | null }[]
  students: {
    student_id: string
    name: string
    email: string
    attended: number
    classes: boolean[]
    not_yet_enrolled?: string[]
  }[]
}

interface SessionAttendance {
  present: number
  total: number
  students: {
    student_id: string
    name: string
    email: string
    present: boolean
    first_seen: string | null
    last_seen: string | null
    sources: ('clip' | 'teams')[]
  }[]
}

const classTime = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString(undefined, {
    day: 'numeric',
    month: 'short',
    hour: 'numeric',
    minute: '2-digit',
  }) : '–'

/** Hands a file the API serves behind sign-in to the browser as a download.
 * The link is put in the page and its URL kept for a minute, as Firefox and
 * Safari can drop a download whose URL is revoked at once. */
async function download(path: string, name: string): Promise<void> {
  const response = await authenticatedFetch(path)
  if (!response.ok) throw new ApiError(response.status, 'DOWNLOAD_FAILED', 'The file could not be downloaded.')
  const url = URL.createObjectURL(await response.blob())
  const link = document.createElement('a')
  link.href = url
  link.download = name
  link.style.display = 'none'
  document.body.append(link)
  link.click()
  link.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
}

/** Who came to each finished class of a course: one row per student, one
 * column per class. For the course's lecturers and admins. */
export function CourseAttendancePanel({ code }: { code: string }) {
  const [data, setData] = useState<CourseAttendance | null>(null)
  const [failed, setFailed] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let current = true
    setData(null)
    setFailed(false)
    apiAuthenticatedGet<CourseAttendance>(`/courses/${encodeURIComponent(code)}/attendance`).then(
      (found) => current && setData(found),
      () => current && setFailed(true),
    )
    return () => {
      current = false
    }
  }, [code])

  const csv = () =>
    download(`/courses/${encodeURIComponent(code)}/attendance.csv`, `attendance-${code}.csv`).catch(
      (caught: unknown) => setError(caught instanceof ApiError ? caught.message : 'The file could not be downloaded.'),
    )

  return (
    <Panel
      title="Attendance"
      description="Present means a join was recorded in C.L.I.P. or Teams. Classes before recorded enrolment are excluded from attendance totals."
      actions={
        data && data.classes.length > 0 ? (
          <button type="button" className={buttonStyles({ intent: 'secondary' })} onClick={() => void csv()}>
            <Download size={15} aria-hidden />
            Download CSV
          </button>
        ) : undefined
      }
    >
      {error && (
        <p role="alert" className="mb-3 text-sm text-critical">
          {error}
        </p>
      )}
      {failed ? (
        <p className="text-sm text-critical">Attendance could not be loaded.</p>
      ) : !data ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : data.classes.length === 0 ? (
        <p className="text-sm text-muted-foreground">No class of this course has finished yet.</p>
      ) : (
        <div className="max-h-[28rem] overflow-auto rounded-md border border-border">
          <table className="w-full border-collapse text-sm">
            <caption className="sr-only">Attendance for {data.course_code}, one column per class</caption>
            <thead className="sticky top-0 z-10 bg-card text-left text-muted-foreground">
              <tr>
                <th scope="col" className="sticky left-0 bg-card px-3 py-2 font-medium">Student</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Attended</th>
                {data.classes.map((item) => (
                  <th key={item.session_id} scope="col" className="px-2 py-2 text-center font-medium">
                    <span className="block">{item.title}</span>
                    <span className="block whitespace-nowrap text-xs">{classTime(item.starts_at)}</span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {data.students.map((row) => {
                const beforeEnrolment = new Set(row.not_yet_enrolled)
                return (
                  <tr key={row.student_id}>
                    <th scope="row" className="sticky left-0 bg-card px-3 py-2 text-left font-medium">
                      <span className="block whitespace-nowrap">{row.name}</span>
                    </th>
                    <td className="px-3 py-2 text-right tabular-nums">
                      {row.attended} of {row.classes.length - beforeEnrolment.size}
                    </td>
                    {row.classes.map((present, index) => {
                      const { session_id: id } = data.classes[index]
                      const label = beforeEnrolment.has(id) ? 'Not yet enrolled' : present ? 'Present' : 'Absent'
                      return (
                        <td key={id} className={`px-2 py-2 text-center ${present ? 'font-semibold text-success' : 'text-muted-foreground'}`}>
                          {label}
                        </td>
                      )
                    })}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  )
}

const seenAt = (iso: string) => new Date(iso).toLocaleString(undefined, {
  dateStyle: 'medium',
  timeStyle: 'short',
})

/** Who was in one class, for its lecturer. */
export function SessionAttendancePanel({ sessionId }: { sessionId: string }) {
  const [attempt, setAttempt] = useState(0)
  const [result, setResult] = useState<{ sessionId: string; attempt: number; data?: SessionAttendance } | null>(null)

  useEffect(() => {
    let current = true
    apiAuthenticatedGet<SessionAttendance>(`/sessions/${encodeURIComponent(sessionId)}/attendance`).then(
      (data) => current && setResult({ sessionId, attempt, data }),
      () => current && setResult({ sessionId, attempt }),
    )
    return () => {
      current = false
    }
  }, [sessionId, attempt])

  const current = result?.sessionId === sessionId && result.attempt === attempt ? result : null
  const data = current?.data
  return (
    <Panel
      title="Who was there"
      description={data && `${data.present} of ${data.total} students. Attendance is based on recorded joins in C.L.I.P. or Teams.`}
      className="mb-6"
    >
      {!current ? (
        <p role="status" className="text-sm text-muted-foreground">Loading attendance…</p>
      ) : !data ? (
        <div className="flex flex-wrap items-center gap-3">
          <p role="alert" className="text-sm text-critical">Attendance could not be loaded.</p>
          <button type="button" className={buttonStyles({ intent: 'secondary' })} onClick={() => setAttempt((count) => count + 1)}>
            Retry attendance
          </button>
        </div>
      ) : (
        <ul className="divide-y divide-border">
          {data.students.map((row) => (
            <li key={row.student_id} className="flex flex-wrap items-center justify-between gap-2 py-2.5">
              <span className="min-w-0">
                <span className="block font-medium">{row.name}</span>
                <span className="block truncate text-xs text-muted-foreground">{row.email}</span>
              </span>
              {row.present ? (
                <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
                  {row.first_seen && <span>First seen <time dateTime={row.first_seen}>{seenAt(row.first_seen)}</time></span>}
                  {row.last_seen && <span>Last seen <time dateTime={row.last_seen}>{seenAt(row.last_seen)}</time></span>}
                  <Tag tone="good">{row.sources.includes('clip') ? 'Present' : 'In Teams only'}</Tag>
                </div>
              ) : (
                <Tag>Absent</Tag>
              )}
            </li>
          ))}
        </ul>
      )}
    </Panel>
  )
}
