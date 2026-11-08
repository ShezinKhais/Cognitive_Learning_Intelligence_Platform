import { useCallback, useEffect, useId, useState, type FormEvent } from 'react'
import { Plus, UserMinus, UserPlus } from 'lucide-react'

import { ApiError, getCurrentUser, type Role } from '../api'
import { buttonStyles } from '../components/ui/button'
import { EmptyState, PageBody, PageHeader, Panel, SkeletonRows, Tag } from '../components/ui/primitives'
import { ProblemState } from '../components/ui/ProblemState'
import { problemArt, problemOf, type Problem } from '../components/ui/problem'
import { useToast } from '../components/ui/toast'
import {
  addStudent,
  getRoster,
  myCourses,
  removeStudent,
  setLecturers,
  type CourseRoster,
} from '../features/courses/coursesApi'
import { AddCourseForm } from '../features/governance/AddCourseForm'
import { listAccounts, type Account, type Course } from '../features/governance/accountsApi'

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
  const [roster, setRoster] = useState<CourseRoster | null>(null)
  const [problem, setProblem] = useState<Problem | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [addingCourse, setAddingCourse] = useState(false)
  const [email, setEmail] = useState('')
  const [lecturers, setLecturerAccounts] = useState<Account[]>([])
  const [students, setStudentAccounts] = useState<Account[]>([])
  const notify = useToast()
  const emailId = useId()
  const courseId = useId()
  const suggestions = useId()
  const isAdmin = role === 'admin'

  useEffect(() => {
    getCurrentUser().then((user) => setRole(user.role), () => setRole(null))
    myCourses().then(
      (found) => {
        setCourses(found)
        setCode((current) => current ?? found[0]?.code ?? null)
      },
      (caught: unknown) => setProblem(problemOf(caught, 'Check your connection and try again.')),
    )
  }, [])

  useEffect(() => {
    if (!isAdmin) return
    listAccounts({ role: 'lecturer', q: '', offset: 0 }).then((page) => setLecturerAccounts(page.items), () => {})
    listAccounts({ role: 'student', q: '', offset: 0 }).then((page) => setStudentAccounts(page.items), () => {})
  }, [isAdmin])

  const load = useCallback(() => {
    if (!code) return
    setRoster(null)
    setError(null)
    getRoster(code).then(setRoster, (caught: unknown) => setError(message(caught, 'The course could not be loaded.')))
  }, [code])
  useEffect(load, [load])

  async function change(action: () => Promise<CourseRoster>, done: string) {
    setBusy(true)
    setError(null)
    try {
      setRoster(await action())
      notify(done)
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
    if (!code || !email.trim()) return
    if (await change(() => addStudent(code, email.trim()), `${email.trim()} added`)) setEmail('')
  }

  function toggleLecturer(id: string) {
    if (!code || !roster) return
    const current = roster.lecturers.map((person) => person.id)
    const next = current.includes(id) ? current.filter((value) => value !== id) : [...current, id]
    void change(() => setLecturers(code, next), 'Lecturers updated')
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
        {courses === null ? (
          <SkeletonRows label="Loading courses" rows={3} />
        ) : courses.length === 0 ? (
          <EmptyState title={isAdmin ? 'No courses yet' : 'You do not teach a course yet'}>
            {isAdmin
              ? 'Add a course, or import a timetable or roster, then assign its lecturers and students here.'
              : 'An admin assigns lecturers to courses. Ask them to add you to yours.'}
          </EmptyState>
        ) : (
          <div className="space-y-6">
            <div className="max-w-sm">
              <label htmlFor={courseId} className="text-sm font-semibold">
                Course
              </label>
              <select
                id={courseId}
                className={`${FIELD} mt-1`}
                value={code ?? ''}
                onChange={(event) => setCode(event.target.value)}
              >
                {courses.map((course) => (
                  <option key={course.id} value={course.code}>
                    {course.code}: {course.name}
                  </option>
                ))}
              </select>
            </div>

            {error && (
              <p role="alert" className="rounded-md border border-critical/30 bg-critical/5 px-4 py-3 text-sm text-critical">
                {error}
              </p>
            )}

            {!roster ? (
              <SkeletonRows label="Loading the course" rows={4} />
            ) : (
              <div className="grid gap-6 lg:grid-cols-[1fr_2fr]">
                <Panel
                  title="Lecturers"
                  description={isAdmin ? 'Who teaches this course and manages its students.' : 'Who teaches this course.'}
                >
                  {isAdmin ? (
                    lecturers.length === 0 ? (
                      <p className="text-sm text-muted-foreground">No lecturer accounts yet.</p>
                    ) : (
                      <ul className="space-y-2">
                        {lecturers.map((person) => (
                          <li key={person.id}>
                            <label className="flex cursor-pointer items-start gap-3 text-sm">
                              <input
                                type="checkbox"
                                className="mt-0.5 size-4 accent-[var(--primary)]"
                                checked={roster.lecturers.some((current) => current.id === person.id)}
                                disabled={busy}
                                onChange={() => toggleLecturer(person.id)}
                              />
                              <span className="min-w-0">
                                <span className="block font-medium">{person.name}</span>
                                <span className="block truncate text-muted-foreground">{person.email}</span>
                              </span>
                            </label>
                          </li>
                        ))}
                      </ul>
                    )
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
                  </form>

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
                              void change(() => removeStudent(roster.course.code, person.id), `${person.name} removed`)
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
          </div>
        )}
      </PageBody>
    </>
  )
}
