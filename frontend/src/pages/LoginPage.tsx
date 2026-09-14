import {
  useState,
  type FormEvent,
} from 'react'
import {
  useLocation,
  useNavigate,
} from 'react-router'

import {
  ApiError,
  login,
  saveAccessToken,
} from '../api'

export default function LoginPage() {
  const navigate = useNavigate()
  const location = useLocation()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function submit(
    event: FormEvent<HTMLFormElement>,
  ): Promise<void> {
    event.preventDefault()
    setSubmitting(true)
    setError(null)

    try {
      const result = await login(
        email.trim(),
        password,
      )

      saveAccessToken(result.access_token)

      const requestedPath = (
        location.state as { from?: string } | null
      )?.from

      const defaultPath =
        result.role === 'student'
          ? '/student'
          : result.role === 'admin'
            ? '/admin'
            : '/lecturer/materials'

      navigate(
        requestedPath ?? defaultPath,
        {
          replace: true,
        },
      )
    } catch (caught: unknown) {
      setError(
        caught instanceof ApiError
          ? caught.message
          : 'Login failed. Check your connection and try again.',
      )
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="min-h-screen grid place-items-center px-6 py-12">
      <form
        onSubmit={submit}
        className="w-full max-w-md rounded-xl border border-border bg-card p-6 shadow-sm"
      >
        <h1 className="text-2xl font-semibold">
          Sign in to C.L.I.P
        </h1>

        <p className="mt-2 text-sm text-muted-foreground">
          Sign in with your registered C.L.I.P account.
        </p>

        <label
          className="mt-6 block text-sm font-medium"
          htmlFor="email"
        >
          Email
        </label>

        <input
          id="email"
          type="email"
          required
          autoComplete="username"
          value={email}
          onChange={(event) =>
            setEmail(event.target.value)
          }
          className="mt-2 w-full rounded-lg border border-border bg-input-background px-3 py-2"
        />

        <label
          className="mt-4 block text-sm font-medium"
          htmlFor="password"
        >
          Password
        </label>

        <input
          id="password"
          type="password"
          required
          autoComplete="current-password"
          value={password}
          onChange={(event) =>
            setPassword(event.target.value)
          }
          className="mt-2 w-full rounded-lg border border-border bg-input-background px-3 py-2"
        />

        {error && (
          <p
            role="alert"
            className="mt-4 text-sm text-critical"
          >
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={submitting}
          className="mt-6 w-full rounded-lg bg-primary px-4 py-2 font-medium text-primary-foreground disabled:opacity-50"
        >
          {submitting ? 'Signing in...' : 'Sign in'}
        </button>
      </form>
    </main>
  )
}
