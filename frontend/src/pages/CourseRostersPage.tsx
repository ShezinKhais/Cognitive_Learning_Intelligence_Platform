import { useCallback, useEffect, useId, useState, type FormEvent } from 'react'
import { Pencil, Plus, Send, UserMinus, UserPlus, Users } from 'lucide-react'

import { ApiError, getCurrentUser, type Role } from '../api'
import { buttonStyles } from '../components/ui/button'
import { EmptyState, PageBody, PageHeader, Panel, SkeletonRows, Tag } from '../components/ui/primitives'
import { ProblemState } from '../components/ui/ProblemState'
import { problemArt, problemOf, type Problem } from '../components/ui/problem'
import { useToast } from '../components/ui/toast'
import { CourseAttendancePanel } from '../features/courses/Attendance'
import {
  addStudent,
  getRoster,
  myCourses,
  removeStudent,
  setLecturers,
  type CourseRoster,
} from '../features/courses/coursesApi'
import BulkRosterPanel from '../features/courses/BulkRosterPanel'
import { CourseRequestsPanel, RequestCourseForm } from '../features/courses/CourseRequestsPanel'
import type { CourseRequest } from '../features/courses/courseRequests'
import { listCourseRequests, renameCourse } from '../features/courses/courseRequestsApi'
import { AddCourseForm } from '../features/governance/AddCourseForm'
import { listAccounts, type Account, type AccountPage, type Course } from '../features/governance/accountsApi'

const FIELD = 'w-full rounded-md border border-input bg-background px-3 py-2 text-sm'

function message(caught: unknown, fallback: string): string {
  return caught instanceof ApiError ? caught.message : fallback
}

/** Which students are on each course, and who teaches it. Students see only
 * the classes of the courses they are on. An admin manages every course and
 * its lecturers; a lecturer manages the students of the courses they teach. */
export default function CourseRostersPage() {
  const [role, setRole] = useState<Role | null>(null)
  const [courses, setCourses] = useState<Course[] | null>(null)
  const [code, setCode] = useState<string | null>(null)
  const [problem, setProblem] = useState<Problem | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [addingCourse, setAddingCourse] = useState(false)
  const [requestingCourse, setRequestingCourse] = useState(false)
  const [requests, setRequests] = useState<CourseRequest[]>([])
  const [renaming, setRenaming] = useState<string | null>(null)
  const notify = useToast()
  const courseId = useId()
  const isAdmin = role === 'admin'

  const loadCourses = useCallback((select?: string) => {
    myCourses().then(
      (found) => {
        setCourses(found)
        setCode((current) => select ?? current ?? found[0]?.code ?? null)
      },
      (caught: unknown) => setProblem(problemOf(caught, 'Check your connection and try again.')),
    )
  }, [])

  useEffect(() => {
    getCurrentUser().then((user) => setRole(user.role), () => setRole(null))
    loadCourses()
    // Requests are a side list: the page works without them.
    listCourseRequests().then(setRequests, () => {})
  }, [loadCourses])

  function decided(request: CourseRequest) {
    setRequests((current) => current.map((item) => (item.id === request.id ? request : item)))
    if (request.status === 'approved') loadCourses(request.code)
  }

  function saveName(event: FormEvent) {
    event.preventDefault()
    if (!code || renaming === null || !renaming.trim()) return
    setBusy(true)
    setError(null)
    renameCourse(code, renaming.trim()).then(
      (course) => {
        setBusy(false)
        setRenaming(null)
        setCourses((current) => (current ?? []).map((item) => (item.id === course.id ? course : item)))
        notify(`Renamed ${course.code}`)
      },
      (caught: unknown) => {
        setBusy(false)
        setError(message(caught, 'The course could not be renamed.'))
      },
    )
  }

  if (problem) {
    return (
      <PageBody>
        <ProblemState art={problemArt(problem.cause)} title="Courses could not be loaded">
          {problem.message}
        </ProblemState>
      </PageBody>
    )
  }

  return (
    <>
      <PageHeader
        title={isAdmin ? 'Courses' : 'My courses'}
        description="Students see only the classes of the courses they are on."
        actions={
          isAdmin && !addingCourse ? (
            <button type="button" className={buttonStyles()} onClick={() => setAddingCourse(true)}>
              <Plus size={16} aria-hidden />
              Add a course
            </button>
          ) : role === 'lecturer' && !requestingCourse ? (
            <button type="button" className={buttonStyles({ intent: 'secondary' })} onClick={() => setRequestingCourse(true)}>
              <Send size={15} aria-hidden />
              Request a course
            </button>
          ) : undefined
        }
      />
      <PageBody>
        {addingCourse && (
          <div className="mb-6">
            <AddCourseForm
              onCancel={() => setAddingCourse(false)}
              onAdded={(course) => {
                setAddingCourse(false)
                setCourses((current) => [...(current ?? []), course].sort((a, b) => a.code.localeCompare(b.code)))
                setCode(course.code)
              }}
            />
          </div>
        )}
        {requestingCourse && (
          <div className="mb-6">
            <RequestCourseForm
              onCancel={() => setRequestingCourse(false)}
              onSent={(request) => {
                setRequestingCourse(false)
                setRequests((current) => [request, ...current])
              }}
            />
          </div>
        )}
        {role && requests.length > 0 && (
          <div className="mb-6">
            <CourseRequestsPanel isAdmin={isAdmin} requests={requests} onDecided={decided} />
          </div>
        )}
        {courses === null ? (
          <SkeletonRows label="Loading courses" rows={3} />
        ) : courses.length === 0 ? (
          <EmptyState title={isAdmin ? 'No courses yet' : 'You do not teach a course yet'}>
            {isAdmin
              ? 'Add a course, or import a timetable or roster, then assign its lecturers and students here.'
              : 'Request a course above, or ask an admin to add you to one that exists.'}
          </EmptyState>
        ) : (
          <div className="space-y-6">
            <div className="flex flex-wrap items-end gap-2">
              <div className="w-full max-w-sm">
                <label htmlFor={courseId} className="text-sm font-semibold">
                  Course
                </label>
                <select
                  id={courseId}
                  className={`${FIELD} mt-1`}
                  value={code ?? ''}
                  onChange={(event) => {
                    setCode(event.target.value)
                    setRenaming(null)
                  }}
                >
                  {courses.map((course) => (
                    <option key={course.id} value={course.code}>
                      {course.code}: {course.name}
                    </option>
                  ))}
                </select>
              </div>
              {isAdmin && renaming === null && (
                <button
                  type="button"
                  className={buttonStyles({ intent: 'quiet' })}
                  onClick={() => setRenaming(courses.find((course) => course.code === code)?.name ?? '')}
                >
                  <Pencil size={15} aria-hidden />
                  Rename
                </button>
              )}
            </div>
            {isAdmin && renaming !== null && (
              <form onSubmit={saveName} className="flex max-w-xl flex-wrap items-end gap-2">
                <div className="min-w-0 flex-1">
                  <label htmlFor={`${courseId}-name`} className="text-sm font-semibold">
                    New name for {code}
                  </label>
                  <input
                    id={`${courseId}-name`}
                    required
                    maxLength={255}
                    value={renaming}
                    onChange={(event) => setRenaming(event.target.value)}
                    className={`${FIELD} mt-1`}
                  />
                </div>
                <button type="submit" className={buttonStyles()} disabled={busy}>
                  Save
                </button>
                <button type="button" className={buttonStyles({ intent: 'secondary' })} onClick={() => setRenaming(null)}>
                  Cancel
                </button>
              </form>
            )}

            {error && (
              <p role="alert" className="rounded-md border border-critical/30 bg-critical/5 px-4 py-3 text-sm text-critical">
                {error}
              </p>
            )}

            {code && <CourseRosterEditor key={code} code={code} isAdmin={isAdmin} />}
          </div>
        )}
      </PageBody>
    </>
  )
}

/** A keyed editor keeps pending reads, saves, and drafts scoped to one course. */
function CourseRosterEditor({ code, isAdmin }: { code: string; isAdmin: boolean }) {
  const [roster, setRoster] = useState<CourseRoster | null>(null)
  const [attempt, setAttempt] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [email, setEmail] = useState('')
  const [bulk, setBulk] = useState(false)
  const [students, setStudentAccounts] = useState<Account[]>([])
  const notify = useToast()
  const emailId = useId()
  const suggestions = useId()

  useEffect(() => {
    if (!isAdmin) return
    let current = true
    listAccounts({ role: 'student', q: '', offset: 0 }).then(
      (page) => current && setStudentAccounts(page.items),
      () => {},
    )
    return () => { current = false }
  }, [isAdmin])

  useEffect(() => {
    let current = true
    getRoster(code).then(
      (data) => current && setRoster(data),
      (caught: unknown) => current && setError(message(caught, 'The course could not be loaded.')),
    )
    return () => { current = false }
  }, [code, attempt])

  async function change(action: () => Promise<CourseRoster>, done: string) {
    setBusy(true)
    setError(null)
    try {
      setRoster(await action())
      notify(`${done} · ${code}`)
      return true
    } catch (caught) {
      setError(message(caught, 'That change was not saved.'))
      return false
    } finally {
      setBusy(false)
    }
  }

  async function add(event: FormEvent) {
    event.preventDefault()
    if (!roster || busy || !email.trim()) return
    if (await change(() => addStudent(code, email.trim()), `${email.trim()} added`)) setEmail('')
  }

  function toggleLecturer(id: string) {
    if (!roster || busy) return
    const current = roster.lecturers.map((person) => person.id)
    const next = current.includes(id) ? current.filter((value) => value !== id) : [...current, id]
    void change(() => setLecturers(code, next), 'Lecturers updated')
  }

  return (
    <>
      {error && (
        <p role="alert" className="rounded-md border border-critical/30 bg-critical/5 px-4 py-3 text-sm text-critical">
          {error}
        </p>
      )}

      {!roster ? (
        error ? (
          <button type="button" className={buttonStyles({ intent: 'secondary' })} onClick={() => {
            setError(null)
            setAttempt((value) => value + 1)
          }}>Retry loading course</button>
        ) : <SkeletonRows label="Loading the course" rows={4} />
      ) : (
        <div className="grid gap-6 lg:grid-cols-[1fr_2fr]">
          <Panel
            title="Lecturers"
            description={isAdmin ? 'Who teaches this course and manages its students.' : 'Who teaches this course.'}
          >
            {isAdmin ? (
              <LecturerPicker roster={roster} busy={busy} onToggle={toggleLecturer} />
            ) : (
              <ul className="space-y-2 text-sm">
                {roster.lecturers.map((person) => (
                  <li key={person.id}>
                    <span className="block font-medium">{person.name}</span>
                    <span className="block truncate text-muted-foreground">{person.email}</span>
                  </li>
                ))}
              </ul>
            )}
          </Panel>

          <Panel
            title={`Students (${roster.students.length})`}
            description="Only these students see this course's classes and get its checkpoints."
          >
            <form onSubmit={add} className="flex flex-wrap items-end gap-2">
              <div className="min-w-0 flex-1">
                <label htmlFor={emailId} className="text-sm font-semibold">
                  Add a student by email
                </label>
                <input
                  id={emailId}
                  type="email"
                  required
                  list={isAdmin ? suggestions : undefined}
                  className={`${FIELD} mt-1`}
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  placeholder="student1@example.edu"
                />
                {isAdmin && (
                  <datalist id={suggestions}>
                    {students.map((person) => (
                      <option key={person.id} value={person.email}>
                        {person.name}
                      </option>
                    ))}
                  </datalist>
                )}
              </div>
              <button type="submit" disabled={busy || !email.trim()} className={buttonStyles()}>
                <UserPlus size={15} aria-hidden />
                Add
              </button>
              {!bulk && (
                <button type="button" className={buttonStyles({ intent: 'secondary' })} onClick={() => setBulk(true)}>
                  <Users size={15} aria-hidden />
                  Add many
                </button>
              )}
            </form>
            {bulk && (
              <BulkRosterPanel
                code={code}
                isAdmin={isAdmin}
                onClose={() => setBulk(false)}
                onDone={(next, added) => {
                  setRoster(next)
                  setBulk(false)
                  notify(`${added} ${added === 1 ? 'student' : 'students'} added to ${code}`)
                }}
              />
            )}

            {roster.students.length === 0 ? (
              <p className="mt-4 text-sm text-muted-foreground">No students on this course yet.</p>
            ) : (
              <ul className="mt-4 divide-y divide-border">
                {roster.students.map((person) => (
                  <li key={person.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                    <span className="min-w-0">
                      <span className="flex items-center gap-2 font-medium">
                        {person.name}
                        {person.home_course && <Tag>Home course</Tag>}
                      </span>
                      <span className="block truncate text-sm text-muted-foreground">{person.email}</span>
                    </span>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() =>
                        void change(() => removeStudent(code, person.id), `${person.name} removed`)
                      }
                      className={buttonStyles({ intent: 'quiet' })}
                    >
                      <UserMinus size={15} aria-hidden />
                      Remove
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </div>
      )}
      {roster && <CourseAttendancePanel code={code} />}
    </>
  )
}

function LecturerPicker({
  roster,
  busy,
  onToggle,
}: {
  roster: CourseRoster
  busy: boolean
  onToggle: (id: string) => void
}) {
  const searchId = useId()
  const [input, setInput] = useState('')
  const [query, setQuery] = useState({ q: '', offset: 0 })
  const [result, setResult] = useState<{ query: typeof query; page?: AccountPage; error?: string } | null>(null)

  useEffect(() => {
    let current = true
    listAccounts({ role: 'lecturer', ...query }).then(
      (page) => current && setResult({ query, page }),
      (caught: unknown) => current && setResult({ query, error: message(caught, 'Lecturers could not be loaded.') }),
    )
    return () => { current = false }
  }, [query])

  const current = result?.query === query ? result : null
  const page = current?.page
  const assigned = new Set(roster.lecturers.map((person) => person.id))
  const available = page?.items.filter((person) => !assigned.has(person.id)) ?? []

  return (
    <>
      {roster.lecturers.length > 0 && (
        <ul className="mb-4 space-y-2 text-sm" aria-label="Assigned lecturers">
          {roster.lecturers.map((person) => (
            <LecturerOption key={person.id} person={person} assigned busy={busy} onToggle={onToggle} />
          ))}
        </ul>
      )}
      <form className="flex flex-wrap items-end gap-2" onSubmit={(event) => {
        event.preventDefault()
        setQuery({ q: input.trim(), offset: 0 })
      }}>
        <div className="min-w-0 flex-1">
          <label htmlFor={searchId} className="text-sm font-semibold">Find a lecturer</label>
          <input id={searchId} type="search" className={`${FIELD} mt-1`} value={input} onChange={(event) => setInput(event.target.value)} />
        </div>
        <button type="submit" className={buttonStyles({ intent: 'secondary' })}>Search</button>
      </form>
      {!current ? (
        <p role="status" className="mt-3 text-sm text-muted-foreground">Loading lecturers…</p>
      ) : current.error ? (
        <div className="mt-3 space-y-2">
          <p role="alert" className="text-sm text-critical">{current.error}</p>
          <button type="button" className={buttonStyles({ intent: 'secondary' })} onClick={() => setQuery({ ...query })}>Retry</button>
        </div>
      ) : page && (
        <div className="mt-3 space-y-3">
          {available.length > 0 ? (
            <ul className="space-y-2 text-sm" aria-label="Available lecturers">
              {available.map((person) => (
                <LecturerOption key={person.id} person={person} assigned={false} busy={busy} onToggle={onToggle} />
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">No additional lecturers on this page.</p>
          )}
          {(page.offset > 0 || page.total > page.limit) && (
            <div className="flex flex-wrap items-center gap-2">
              <button type="button" disabled={page.offset === 0} className={buttonStyles({ intent: 'secondary' })}
                onClick={() => setQuery({ q: query.q, offset: Math.max(0, page.offset - page.limit) })}>
                Previous
              </button>
              <span className="text-xs text-muted-foreground">{page.items.length ? `${page.offset + 1}–${page.offset + page.items.length}` : '0'} of {page.total}</span>
              <button type="button" disabled={page.offset + page.limit >= page.total} className={buttonStyles({ intent: 'secondary' })}
                onClick={() => setQuery({ q: query.q, offset: page.offset + page.limit })}>
                Next
              </button>
            </div>
          )}
        </div>
      )}
    </>
  )
}

function LecturerOption({
  person,
  assigned,
  busy,
  onToggle,
}: {
  person: { id: string; name: string; email: string }
  assigned: boolean
  busy: boolean
  onToggle: (id: string) => void
}) {
  return (
    <li>
      <label className="flex cursor-pointer items-start gap-3 text-sm">
        <input type="checkbox" className="mt-0.5 size-4 accent-[var(--primary)]"
          checked={assigned} disabled={busy} onChange={() => onToggle(person.id)} />
        <span className="min-w-0">
          <span className="block font-medium">{person.name}</span>
          <span className="block truncate text-muted-foreground">{person.email}</span>
        </span>
      </label>
    </li>
  )
}
