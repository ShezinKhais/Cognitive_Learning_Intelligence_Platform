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
          This page is not available to your account
        </h1>

        <p className="mt-2 text-sm text-muted-foreground">
          Each workspace is open only to the role it is for. Sign in with an
          account that has access, or go back to your own home page.
        </p>

        <div className="mt-6 flex justify-center gap-3">
          <button
            type="button"
            onClick={() => navigate('/', { replace: true })}
            className="rounded-lg border border-border px-4 py-2 text-sm font-medium"
          >
            My home page
          </button>
          <button
            type="button"
            onClick={signInWithAnotherAccount}
            className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground"
          >
            Sign in with another account
          </button>
        </div>
      </div>
    </main>
  )
}
