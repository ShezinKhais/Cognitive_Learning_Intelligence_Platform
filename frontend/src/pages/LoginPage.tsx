import { useState, type FormEvent } from 'react'
import { motion } from 'motion/react'
import { useLocation, useNavigate } from 'react-router'

import { ApiError, getCurrentUser, login, saveAccessToken } from '../api'
import { hasRequiredConsent, intendedPathForRole } from '../authRouting'
import { Wordmark } from '../components/brand/ClipMark'
import { requestIntro } from '../components/shell/intro'
import { buttonStyles } from '../components/ui/button'
import { cn } from '../components/ui/cn'

// A class answering a run of questions: the share right, then wrong.
// The development accounts from the README, offered only in a development
// build so a demo does not start with typing. Never part of production.
const DEMO_ACCOUNTS = import.meta.env.DEV
  ? [
      { role: 'Lecturer', email: 'lecturer@clip.example.com', password: 'LecturerPass123!' },
      { role: 'Student', email: 'student@clip.example.com', password: 'StudentPass123!' },
      { role: 'Administrator', email: 'admin@clip.example.com', password: 'AdminPass123!' },
    ]
  : []

const STRIP = [
  [0.8, 0.15], [0.62, 0.3], [0.9, 0.08], [0.45, 0.45], [0.7, 0.22], [0.86, 0.1], [0.58, 0.3], [0.93, 0.05],
] as const

export default function LoginPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      const result = await login(email.trim(), password)
      saveAccessToken(result.access_token, result.expires_in)
      requestIntro()
      const currentUser = await getCurrentUser()
      const requestedPath = (location.state as { from?: string } | null)?.from
      const destination = intendedPathForRole(currentUser.role, requestedPath)
      if (!hasRequiredConsent(currentUser)) {
        navigate('/consent', { replace: true, state: { from: destination } })
        return
      }
      navigate(destination, { replace: true })
    } catch (caught: unknown) {
      setError(caught instanceof ApiError ? caught.message : 'Sign-in failed. Check your connection and try again.')
    } finally {
      setSubmitting(false)
    }
  }

  const field = 'mt-1.5 w-full rounded-md border border-input bg-input-background px-3 py-2.5 transition-colors focus:border-primary'

  return (
    <main className="grid min-h-screen bg-background lg:grid-cols-[1.1fr_1fr]">
      <section className="relative hidden flex-col justify-between overflow-hidden border-r border-border bg-card px-14 py-12 lg:flex">
        <Wordmark />
        <div>
          <h1 className="max-w-md text-[2.6rem] font-extrabold leading-[1.1]">Know how the class is doing while you are still teaching it.</h1>
          <p className="mt-4 max-w-md text-lg text-muted-foreground">
            Questions drawn from your slides, answered live, and the topics that tripped the room up, before the lecture ends.
          </p>
          <ol className="mt-10 flex h-28 items-end gap-2" aria-hidden>
            {STRIP.map(([right, wrong], index) => (
              <li key={index} className="flex h-full w-5 flex-col-reverse overflow-hidden rounded bg-muted">
                <motion.span
                  className="block bg-success"
                  initial={{ height: 0 }}
                  animate={{ height: `${right * 100}%` }}
                  transition={{ delay: 0.25 + index * 0.09, type: 'spring', stiffness: 160, damping: 18 }}
                />
                <motion.span
                  className="block bg-critical/80"
                  initial={{ height: 0 }}
                  animate={{ height: `${wrong * 100}%` }}
                  transition={{ delay: 0.35 + index * 0.09, type: 'spring', stiffness: 160, damping: 18 }}
                />
              </li>
            ))}
            <motion.li
              className="ml-1 h-full w-5 rounded bg-highlight"
              initial={{ opacity: 0 }}
              animate={{ opacity: [0, 1, 0.55, 1] }}
              transition={{ delay: 1.1, duration: 1.6, repeat: Infinity, repeatType: 'reverse' }}
            />
          </ol>
          <p className="mt-3 text-sm text-muted-foreground">Each tick is a question; the last one is still open.</p>
        </div>
        <p className="text-sm text-muted-foreground">Works in the browser and inside Microsoft Teams.</p>
      </section>

      <section className="flex flex-col justify-center px-6 py-12 sm:px-12">
        <div className="mx-auto w-full max-w-sm">
          <div className="mb-10 lg:hidden">
            <Wordmark />
          </div>
          <h2 className="text-2xl font-bold">Sign in</h2>
          <p className="mt-1 text-muted-foreground">With your C.L.I.P account.</p>
          <form onSubmit={submit} className="mt-8 space-y-4">
            <label className="block text-sm font-semibold">
              Email
              <input
                type="email"
                required
                autoComplete="username"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                className={field}
              />
            </label>
            <label className="block text-sm font-semibold">
              Password
              <input
                type="password"
                required
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                className={field}
              />
            </label>
            {error && (
              <motion.p role="alert" initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} className="text-sm text-critical">
                {error}
              </motion.p>
            )}
            <button type="submit" disabled={submitting} className={cn(buttonStyles(), 'w-full py-2.5')}>
              {submitting ? 'Signing in…' : 'Sign in'}
            </button>
          </form>
          {DEMO_ACCOUNTS.length > 0 && (
            <div className="mt-8 border-t border-border pt-5">
              <p className="text-sm text-muted-foreground">Development build: fill in a demo account</p>
              <div className="mt-2 flex flex-wrap gap-2">
                {DEMO_ACCOUNTS.map((account) => (
                  <button
                    key={account.role}
                    type="button"
                    className={buttonStyles({ intent: 'secondary' })}
                    onClick={() => {
                      setEmail(account.email)
                      setPassword(account.password)
                    }}
                  >
                    {account.role}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </section>
    </main>
  )
}
