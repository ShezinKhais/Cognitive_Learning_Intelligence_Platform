import { useEffect, useState } from 'react'
import { Download } from 'lucide-react'

import { ApiError, apiAuthenticatedGet, authenticatedFetch } from '../../api'
import { buttonStyles } from '../../components/ui/button'
import { Panel, Tag } from '../../components/ui/primitives'

interface CourseAttendance {
  course_code: string
  classes: { session_id: string; title: string; starts_at: string | null }[]
  students: { student_id: string; name: string; email: string; attended: number; classes: boolean[] }[]
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
    minutes: number | null
    sources: ('clip' | 'teams')[]
  }[]
}

const day = (iso: string | null) =>
  iso ? new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short' }) : '–'

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
      description="Present means the student joined the class in C.L.I.P or was seen joining its Teams meeting."
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
                  <th key={item.session_id} scope="col" className="whitespace-nowrap px-2 py-2 text-center font-medium" title={item.title}>
                    {day(item.starts_at)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {data.students.map((row) => (
                <tr key={row.student_id}>
                  <th scope="row" className="sticky left-0 bg-card px-3 py-2 text-left font-medium">
                    <span className="block whitespace-nowrap">{row.name}</span>
                  </th>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {row.attended} of {row.classes.length}
                  </td>
                  {row.classes.map((present, index) => (
                    <td key={data.classes[index].session_id} className="px-2 py-2 text-center">
                      <span
                        aria-label={present ? 'Present' : 'Absent'}
                        title={`${data.classes[index].title}: ${present ? 'present' : 'absent'}`}
                        className={present ? 'font-semibold text-success' : 'text-muted-foreground'}
                      >
                        {present ? '✓' : '·'}
                      </span>
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  )
}

/** Who was in one class, for its lecturer. */
export function SessionAttendancePanel({ sessionId }: { sessionId: string }) {
  const [data, setData] = useState<SessionAttendance | null>(null)

  useEffect(() => {
    let current = true
    apiAuthenticatedGet<SessionAttendance>(`/sessions/${encodeURIComponent(sessionId)}/attendance`).then(
      (found) => current && setData(found),
      () => {},
    )
    return () => {
      current = false
    }
  }, [sessionId])

  if (!data) return null
  return (
    <Panel
      title="Who was there"
      description={`${data.present} of ${data.total} students. Joined in C.L.I.P or seen joining the Teams meeting.`}
      className="mb-6"
    >
      <ul className="divide-y divide-border">
        {data.students.map((row) => (
          <li key={row.student_id} className="flex flex-wrap items-center justify-between gap-2 py-2.5">
            <span className="min-w-0">
              <span className="block font-medium">{row.name}</span>
              <span className="block truncate text-xs text-muted-foreground">{row.email}</span>
            </span>
            {row.present ? (
              <span className="flex items-center gap-2 text-sm text-muted-foreground">
                {row.minutes !== null && `${row.minutes} min`}
                <Tag tone="good">{row.sources.includes('clip') ? 'Present' : 'In Teams only'}</Tag>
              </span>
            ) : (
              <Tag>Absent</Tag>
            )}
          </li>
        ))}
      </ul>
    </Panel>
  )
}
