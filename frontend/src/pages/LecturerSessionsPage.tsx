import {
  useState,
  type FormEvent,
} from 'react'
import {
  ArrowRight,
  Radio,
} from 'lucide-react'
import {
  Link,
  useNavigate,
} from 'react-router'

import {
  ApiError,
  clearAccessToken,
} from '../api'
import SignOutButton from '../components/SignOutButton'
import { createSession } from '../features/live/sessionActions'

export default function LecturerSessionsPage() {
  const navigate = useNavigate()

  const [
    courseCode,
    setCourseCode,
  ] = useState('')

  const [
    title,
    setTitle,
  ] = useState('')

  const [
    creating,
    setCreating,
  ] = useState(false)

  const [
    error,
    setError,
  ] = useState<string | null>(null)

  async function handleSubmit(
    event: FormEvent<HTMLFormElement>,
  ) {
    event.preventDefault()

    const cleanCourseCode =
      courseCode.trim()

    const cleanTitle =
      title.trim()

    if (!cleanCourseCode) {
      setError(
        'Enter the course code for this session.',
      )
      return
    }

    if (!cleanTitle) {
      setError(
        'Enter a title for this session.',
      )
      return
    }

    setCreating(true)
    setError(null)

    try {
      const session =
        await createSession({
          course_code:
            cleanCourseCode,
          title: cleanTitle,
        })

      navigate(
        `/lecturer/sessions/${session.id}/live`,
      )
    } catch (caught: unknown) {
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
          : 'The session could not be created. Check your connection and try again.',
      )
    } finally {
      setCreating(false)
    }
  }

  return (
    <main className="min-h-screen bg-background">
      <header className="border-b border-border bg-card">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-5 py-4 sm:px-8">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
              C.L.I.P lecturer workspace
            </p>

            <h1 className="mt-1 text-xl font-bold text-card-foreground">
              Live Sessions
            </h1>
          </div>

          <div className="flex items-center gap-3">
            <Link
              to="/lecturer/materials"
              className="rounded-lg border border-border px-3 py-2 text-sm font-medium hover:bg-muted"
            >
              Materials
            </Link>

            <SignOutButton />
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-6xl px-5 py-8 sm:px-8">
        <div className="max-w-2xl">
          <div className="flex items-center gap-3">
            <div className="grid size-11 place-items-center rounded-xl bg-info/10 text-info">
              <Radio
                aria-hidden="true"
                size={22}
              />
            </div>

            <div>
              <h2 className="text-2xl font-semibold tracking-tight">
                Prepare a live class
              </h2>

              <p className="mt-1 text-sm leading-6 text-muted-foreground">
                Create the session first, then open the live workspace to start and manage it.
              </p>
            </div>
          </div>
        </div>

        <section className="mt-8 max-w-2xl rounded-2xl border border-border bg-card p-6 shadow-[var(--shadow-card)]">
          <h3 className="text-lg font-semibold">
            New live session
          </h3>

          <p className="mt-1 text-sm leading-6 text-muted-foreground">
            Use the same course code as the lecture material prepared for this class.
          </p>

          <form
            className="mt-6 space-y-5"
            onSubmit={
              handleSubmit
            }
          >
            <div>
              <label
                htmlFor="course-code"
                className="text-sm font-medium"
              >
                Course code
              </label>

              <input
                id="course-code"
                type="text"
                value={courseCode}
                onChange={(event) =>
                  setCourseCode(
                    event.target.value,
                  )
                }
                placeholder="Example: CLIP101"
                autoComplete="off"
                disabled={creating}
                className="mt-2 w-full rounded-lg border border-border bg-background px-4 py-3 text-sm outline-none ring-offset-background focus:ring-2 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-60"
              />
            </div>

            <div>
              <label
                htmlFor="session-title"
                className="text-sm font-medium"
              >
                Session title
              </label>

              <input
                id="session-title"
                type="text"
                value={title}
                onChange={(event) =>
                  setTitle(
                    event.target.value,
                  )
                }
                placeholder="Example: Network Security Lecture"
                autoComplete="off"
                disabled={creating}
                className="mt-2 w-full rounded-lg border border-border bg-background px-4 py-3 text-sm outline-none ring-offset-background focus:ring-2 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-60"
              />
            </div>

            {error && (
              <div
                role="alert"
                className="rounded-lg border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-destructive"
              >
                {error}
              </div>
            )}

            <div className="flex flex-wrap items-center justify-between gap-4 pt-2">
              <p className="max-w-md text-xs leading-5 text-muted-foreground">
                The session will be created in prepared state. It will not begin until you start it from the live workspace.
              </p>

              <button
                type="submit"
                disabled={creating}
                className="inline-flex items-center gap-2 rounded-lg bg-primary px-5 py-2.5 text-sm font-medium text-primary-foreground disabled:cursor-not-allowed disabled:opacity-50"
              >
                {creating
                  ? 'Creating...'
                  : 'Create session'}

                {!creating && (
                  <ArrowRight
                    aria-hidden="true"
                    size={16}
                  />
                )}
              </button>
            </div>
          </form>
        </section>
      </div>
    </main>
  )
}