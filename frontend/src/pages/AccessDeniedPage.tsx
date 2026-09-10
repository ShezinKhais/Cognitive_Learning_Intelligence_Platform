import { useNavigate } from 'react-router'

import { clearAccessToken } from '../api'

export default function AccessDeniedPage() {
  const navigate = useNavigate()

  function signInWithAnotherAccount(): void {
    clearAccessToken()

    navigate(
      '/login',
      {
        replace: true,
      },
    )
  }

  return (
    <main className="min-h-screen grid place-items-center p-8">
      <div className="w-full max-w-md rounded-xl border border-border bg-card p-6 text-center">
        <h1 className="text-xl font-bold">
          Student access required
        </h1>

        <p className="mt-2 text-sm text-muted-foreground">
          The student workspace is only available to accounts
          with the student role.
        </p>

        <button
          type="button"
          onClick={signInWithAnotherAccount}
          className="mt-6 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground"
        >
          Sign in with another account
        </button>
      </div>
    </main>
  )
}
