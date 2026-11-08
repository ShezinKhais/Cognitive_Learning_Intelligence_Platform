import { useCallback, useEffect, useId, useState, type FormEvent } from 'react'
import { Copy, KeyRound, Plus, Search } from 'lucide-react'

import { ApiError, getCurrentUser, type Role } from '../api'
import { buttonStyles } from '../components/ui/button'
import { EmptyState, MetaLine, PageBody, PageHeader, Panel, SkeletonRows, Tag } from '../components/ui/primitives'
import { ProblemState } from '../components/ui/ProblemState'
import { problemArt, problemOf, type Problem } from '../components/ui/problem'
import SegmentedTabs from '../components/ui/SegmentedTabs'
import { useToast } from '../components/ui/toast'
import {
  createAccount,
  createCourse,
  listAccounts,
  listCourses,
  resetPassword,
  updateAccount,
  type Account,
  type AccountIssued,
  type Course,
} from '../features/governance/accountsApi'

type RoleFilter = 'all' | Role
const ROLE_WORD: Record<Role, string> = { student: 'Student', lecturer: 'Lecturer', admin: 'Admin' }
const FIELD = 'mt-1 w-full rounded-md border border-input bg-background px-3 py-2 text-sm'

function message(caught: unknown, fallback: string): string {
  return caught instanceof ApiError ? caught.message : fallback
}

/** Everyone who can use C.L.I.P: add people, enrol students, swap lecturer
 * and admin, switch accounts off, and issue website passwords. */
export default function AdminAccountsPage() {
  const [role, setRole] = useState<RoleFilter>('all')
  const [query, setQuery] = useState('')
  const [search, setSearch] = useState('')
  const [offset, setOffset] = useState(0)
  const [page, setPage] = useState<{ items: Account[]; total: number } | null>(null)
  const [courses, setCourses] = useState<Course[]>([])
  const [error, setError] = useState<Problem | null>(null)
  const [adding, setAdding] = useState<'person' | 'course' | null>(null)
  const [issued, setIssued] = useState<AccountIssued | null>(null)
  const [me, setMe] = useState<string | null>(null)

  const load = useCallback(() => {
    setError(null)
    listAccounts({ role: role === 'all' ? null : role, q: search, offset }).then(
      (found) => setPage({ items: found.items, total: found.total }),
      (caught: unknown) => setError(problemOf(caught, 'Check your connection and try again.')),
    )
  }, [role, search, offset])

  useEffect(load, [load])
  useEffect(() => {
    listCourses().then(setCourses, () => setCourses([]))
    getCurrentUser().then((user) => setMe(user.id), () => setMe(null))
  }, [])

  function replace(account: Account) {
    setPage((current) =>
      current && { ...current, items: current.items.map((item) => (item.id === account.id ? account : item)) },
    )
  }

  return (
    <>
      <PageHeader
        title="Accounts"
        description="Everyone who can sign in. Teams finds a person by their email, so add them here before they open C.L.I.P in Teams."
        actions={
          <div className="flex flex-wrap gap-2">
            <button type="button" className={buttonStyles({ intent: 'secondary' })} onClick={() => setAdding('course')}>
              Add a course
            </button>
            <button type="button" className={buttonStyles()} onClick={() => setAdding('person')}>
              <Plus size={16} aria-hidden />
              Add a person
            </button>
          </div>
        }
      />
      <PageBody>
        <div className="space-y-4">
          {issued && <IssuedPassword issued={issued} onDone={() => setIssued(null)} />}

          {adding === 'person' && (
            <AddPerson
              courses={courses}
              onCancel={() => setAdding(null)}
              onAdded={(result) => {
                setAdding(null)
                if (result.password) setIssued(result)
                load()
              }}
            />
          )}
          {adding === 'course' && (
            <AddCourse
              onCancel={() => setAdding(null)}
              onAdded={(course) => {
                setAdding(null)
                setCourses((current) => [...current, course].sort((a, b) => a.code.localeCompare(b.code)))
              }}
            />
          )}

          <div className="flex flex-wrap items-center gap-3">
            <SegmentedTabs
              label="Show"
              value={role}
              onChange={(next) => {
                setOffset(0)
                setRole(next)
              }}
              segments={[
                { key: 'all', label: 'Everyone' },
                { key: 'student', label: 'Students' },
                { key: 'lecturer', label: 'Lecturers' },
                { key: 'admin', label: 'Admins' },
              ]}
            />
            <form
              role="search"
              className="relative min-w-0 flex-1 sm:max-w-xs"
              onSubmit={(event) => {
                event.preventDefault()
                setOffset(0)
                setSearch(query)
              }}
            >
              <Search size={16} aria-hidden className="absolute top-1/2 left-3 -translate-y-1/2 text-muted-foreground" />
              <input
                type="search"
                aria-label="Find by name or email"
                placeholder="Name or email"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                className="w-full rounded-md border border-input bg-card py-2 pr-3 pl-9 text-sm"
              />
            </form>
          </div>

          {error ? (
            <ProblemState art={problemArt(error.cause)} title="Accounts could not be loaded" retry={load}>
              {error.message}
            </ProblemState>
          ) : !page ? (
            <SkeletonRows label="Loading accounts" />
          ) : page.items.length === 0 ? (
            <EmptyState title={search ? 'Nobody matches' : 'No accounts yet'}>
              {search ? 'Try part of their name or email.' : 'Add a person to get started.'}
            </EmptyState>
          ) : (
            <>
              <ul className="space-y-2">
                {page.items.map((account) => (
                  <li key={account.id}>
                    <AccountRow
                      account={account}
                      isSelf={account.id === me}
                      courses={courses}
                      onChanged={replace}
                      onIssued={setIssued}
                    />
                  </li>
                ))}
              </ul>
              {page.total > 50 && (
                <div className="flex items-center justify-between text-sm text-muted-foreground">
                  <span>
                    {offset + 1} to {Math.min(offset + 50, page.total)} of {page.total}
                  </span>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      className={buttonStyles({ intent: 'secondary' })}
                      disabled={offset === 0}
                      onClick={() => setOffset(offset - 50)}
                    >
                      Previous
                    </button>
                    <button
                      type="button"
                      className={buttonStyles({ intent: 'secondary' })}
                      disabled={offset + 50 >= page.total}
                      onClick={() => setOffset(offset + 50)}
                    >
                      Next
                    </button>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </PageBody>
    </>
  )
}

function AccountRow({
  account,
  isSelf,
  courses,
  onChanged,
  onIssued,
}: {
  account: Account
  isSelf: boolean
  courses: Course[]
  onChanged: (account: Account) => void
  onIssued: (issued: AccountIssued) => void
}) {
  const notify = useToast()
  const [editing, setEditing] = useState(false)
  const [busy, setBusy] = useState(false)

  function run<T>(action: () => Promise<T>, done: (value: T) => void) {
    setBusy(true)
    action().then(
      (value) => {
        setBusy(false)
        done(value)
      },
      (caught: unknown) => {
        setBusy(false)
        notify(message(caught, 'That could not be saved. Try again.'), { tone: 'problem' })
      },
    )
  }

  const isStaff = account.role !== 'student'
  return (
    <article className="rounded-lg border border-border bg-card px-5 py-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className={`font-semibold ${account.active ? '' : 'text-muted-foreground line-through'}`}>{account.name}</h2>
          <MetaLine
            items={[
              <span key="email" className="break-all whitespace-normal">{account.email}</span>,
              account.course?.code,
              account.teams_linked ? 'Signed in through Teams' : 'Not yet in Teams',
              account.has_password ? 'Website sign-in' : null,
            ]}
          />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {!account.active && <Tag tone="poor">Switched off</Tag>}
          <Tag tone={account.role === 'admin' ? 'info' : 'neutral'}>{ROLE_WORD[account.role]}</Tag>
        </div>
      </div>

      {editing ? (
        <EditAccount
          account={account}
          isSelf={isSelf}
          courses={courses}
          busy={busy}
          onCancel={() => setEditing(false)}
          onSave={(change) =>
            run(
              () => updateAccount(account.id, change),
              (saved) => {
                onChanged(saved)
                setEditing(false)
                notify(`Saved ${saved.name}`)
              },
            )
          }
        />
      ) : (
        <div className="mt-3 flex flex-wrap gap-2">
          <button type="button" className={buttonStyles({ intent: 'secondary' })} onClick={() => setEditing(true)}>
            Edit
          </button>
          {!isSelf && (
            <button
              type="button"
              className={buttonStyles({ intent: account.active ? 'danger' : 'secondary' })}
              disabled={busy}
              onClick={() =>
                run(
                  () => updateAccount(account.id, { active: !account.active }),
                  (saved) => {
                    onChanged(saved)
                    notify(saved.active ? `${saved.name} can sign in again` : `${saved.name} is switched off`)
                  },
                )
              }
            >
              {account.active ? 'Switch off' : 'Switch on'}
            </button>
          )}
          {(isStaff || account.has_password) && (
            <button
              type="button"
              className={buttonStyles({ intent: 'quiet' })}
              disabled={busy}
              onClick={() =>
                run(
                  () => resetPassword(account.id),
                  (result) => {
                    onChanged(result.account)
                    onIssued(result)
                  },
                )
              }
            >
              <KeyRound size={16} aria-hidden />
              {account.has_password ? 'New website password' : 'Give a website password'}
            </button>
          )}
        </div>
      )}
    </article>
  )
}

function EditAccount({
  account,
  isSelf,
  courses,
  busy,
  onCancel,
  onSave,
}: {
  account: Account
  isSelf: boolean
  courses: Course[]
  busy: boolean
  onCancel: () => void
  onSave: (change: { name?: string; role?: Role; course_id?: string }) => void
}) {
  const [name, setName] = useState(account.name)
  const [role, setRole] = useState<Role>(account.role)
  const [courseId, setCourseId] = useState(account.course?.id ?? '')
  const nameId = useId()
  const roleId = useId()
  const courseFieldId = useId()

  function submit(event: FormEvent) {
    event.preventDefault()
    onSave({
      ...(name.trim() !== account.name ? { name: name.trim() } : {}),
      ...(role !== account.role ? { role } : {}),
      ...(courseId && courseId !== account.course?.id ? { course_id: courseId } : {}),
    })
  }

  return (
    <form onSubmit={submit} className="mt-4 grid gap-3 sm:grid-cols-2">
      <div>
        <label htmlFor={nameId} className="text-sm font-semibold">
          Name
        </label>
        <input id={nameId} required maxLength={100} value={name} onChange={(e) => setName(e.target.value)} className={FIELD} />
      </div>
      {account.role === 'student' ? (
        <div>
          <label htmlFor={courseFieldId} className="text-sm font-semibold">
            Course
          </label>
          <select id={courseFieldId} value={courseId} onChange={(e) => setCourseId(e.target.value)} className={FIELD}>
            {courses.map((course) => (
              <option key={course.id} value={course.id}>
                {course.code}: {course.name}
              </option>
            ))}
          </select>
        </div>
      ) : (
        <div>
          <label htmlFor={roleId} className="text-sm font-semibold">
            Role
          </label>
          <select
            id={roleId}
            value={role}
            disabled={isSelf}
            onChange={(e) => setRole(e.target.value as Role)}
            className={FIELD}
          >
            <option value="lecturer">Lecturer</option>
            <option value="admin">Admin</option>
          </select>
        </div>
      )}
      <div className="flex gap-2 sm:col-span-2">
        <button type="submit" className={buttonStyles()} disabled={busy}>
          {busy ? 'Saving…' : 'Save'}
        </button>
        <button type="button" className={buttonStyles({ intent: 'secondary' })} onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  )
}

function AddPerson({
  courses,
  onCancel,
  onAdded,
}: {
  courses: Course[]
  onCancel: () => void
  onAdded: (result: AccountIssued) => void
}) {
  const notify = useToast()
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<Role>('student')
  const [courseId, setCourseId] = useState(courses[0]?.id ?? '')
  const [password, setPassword] = useState(false)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const ids = { name: useId(), email: useId(), role: useId(), course: useId(), password: useId() }

  useEffect(() => {
    if (!courseId && courses[0]) setCourseId(courses[0].id)
  }, [courses, courseId])

  function submit(event: FormEvent) {
    event.preventDefault()
    setSending(true)
    setError(null)
    createAccount({
      name,
      email,
      role,
      course_id: role === 'student' ? courseId || null : null,
      website_password: role === 'student' ? password : true,
    }).then(
      (result) => {
        notify(`Added ${result.account.name}`)
        onAdded(result)
      },
      (caught: unknown) => {
        setSending(false)
        setError(message(caught, 'The account could not be added. Try again.'))
      },
    )
  }

  return (
    <Panel title="Add a person" description="Use the email they sign in to Microsoft 365 with.">
      <form onSubmit={submit} className="grid gap-3 sm:grid-cols-2">
        <div>
          <label htmlFor={ids.name} className="text-sm font-semibold">
            Name
          </label>
          <input id={ids.name} required maxLength={100} value={name} onChange={(e) => setName(e.target.value)} className={FIELD} />
        </div>
        <div>
          <label htmlFor={ids.email} className="text-sm font-semibold">
            Email
          </label>
          <input
            id={ids.email}
            type="email"
            required
            maxLength={255}
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className={FIELD}
          />
        </div>
        <div>
          <label htmlFor={ids.role} className="text-sm font-semibold">
            Role
          </label>
          <select id={ids.role} value={role} onChange={(e) => setRole(e.target.value as Role)} className={FIELD}>
            <option value="student">Student</option>
            <option value="lecturer">Lecturer</option>
            <option value="admin">Admin</option>
          </select>
        </div>
        {role === 'student' && (
          <div>
            <label htmlFor={ids.course} className="text-sm font-semibold">
              Course
            </label>
            {courses.length === 0 ? (
              <p className="mt-2 text-sm text-critical">Add a course first.</p>
            ) : (
              <select id={ids.course} value={courseId} onChange={(e) => setCourseId(e.target.value)} className={FIELD}>
                {courses.map((course) => (
                  <option key={course.id} value={course.id}>
                    {course.code}: {course.name}
                  </option>
                ))}
              </select>
            )}
          </div>
        )}
        {role === 'student' ? (
          <label htmlFor={ids.password} className="flex items-start gap-2 text-sm sm:col-span-2">
            <input
              id={ids.password}
              type="checkbox"
              className="mt-1"
              checked={password}
              onChange={(e) => setPassword(e.target.checked)}
            />
            Also give a website password. Students in Teams do not need one.
          </label>
        ) : (
          <p className="text-sm text-muted-foreground sm:col-span-2">
            Staff get a website password for the dashboards. It is shown once, after you add them.
          </p>
        )}
        {error && (
          <p role="alert" className="text-sm text-critical sm:col-span-2">
            {error}
          </p>
        )}
        <div className="flex gap-2 sm:col-span-2">
          <button
            type="submit"
            className={buttonStyles()}
            disabled={sending || (role === 'student' && !courseId)}
          >
            {sending ? 'Adding…' : 'Add'}
          </button>
          <button type="button" className={buttonStyles({ intent: 'secondary' })} onClick={onCancel}>
            Cancel
          </button>
        </div>
      </form>
    </Panel>
  )
}

function AddCourse({ onCancel, onAdded }: { onCancel: () => void; onAdded: (course: Course) => void }) {
  const notify = useToast()
  const [code, setCode] = useState('')
  const [name, setName] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const codeId = useId()
  const nameId = useId()

  function submit(event: FormEvent) {
    event.preventDefault()
    setSending(true)
    setError(null)
    createCourse({ code: code.trim(), name: name.trim() }).then(
      (course) => {
        notify(`Added ${course.code}`)
        onAdded(course)
      },
      (caught: unknown) => {
        setSending(false)
        setError(message(caught, 'The course could not be added. Try again.'))
      },
    )
  }

  return (
    <Panel title="Add a course">
      <form onSubmit={submit} className="grid gap-3 sm:grid-cols-[10rem_1fr]">
        <div>
          <label htmlFor={codeId} className="text-sm font-semibold">
            Code
          </label>
          <input
            id={codeId}
            required
            minLength={2}
            maxLength={20}
            pattern="[A-Za-z0-9_\-]+"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            className={FIELD}
          />
        </div>
        <div>
          <label htmlFor={nameId} className="text-sm font-semibold">
            Name
          </label>
          <input id={nameId} required maxLength={255} value={name} onChange={(e) => setName(e.target.value)} className={FIELD} />
        </div>
        {error && (
          <p role="alert" className="text-sm text-critical sm:col-span-2">
            {error}
          </p>
        )}
        <div className="flex gap-2 sm:col-span-2">
          <button type="submit" className={buttonStyles()} disabled={sending}>
            {sending ? 'Adding…' : 'Add'}
          </button>
          <button type="button" className={buttonStyles({ intent: 'secondary' })} onClick={onCancel}>
            Cancel
          </button>
        </div>
      </form>
    </Panel>
  )
}

function IssuedPassword({ issued, onDone }: { issued: AccountIssued; onDone: () => void }) {
  const [copied, setCopied] = useState(false)
  return (
    <Panel
      title={`Website password for ${issued.account.name}`}
      description="Shown this once. Give it to them in person, not by chat or email."
    >
      <div className="flex flex-wrap items-center gap-2">
        <code className="rounded-md bg-muted px-3 py-2 font-mono text-sm break-all">{issued.password}</code>
        <button
          type="button"
          className={buttonStyles({ intent: 'secondary' })}
          onClick={() => {
            void navigator.clipboard?.writeText(issued.password ?? '').then(() => setCopied(true))
          }}
        >
          <Copy size={16} aria-hidden />
          {copied ? 'Copied' : 'Copy'}
        </button>
        <button type="button" className={buttonStyles({ intent: 'quiet' })} onClick={onDone}>
          Done
        </button>
      </div>
    </Panel>
  )
}
