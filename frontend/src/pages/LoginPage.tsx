import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { animate, motion, useAnimationControls, useReducedMotion } from 'motion/react'
import { AlertCircle, ArrowRight, Eye, EyeOff, LoaderCircle } from 'lucide-react'
import { useLocation, useNavigate } from 'react-router'

import { ApiError, getCurrentUser, login, saveAccessToken } from '../api'
import { hasRequiredConsent, intendedPathForRole } from '../authRouting'
import { Wordmark } from '../components/brand/ClipMark'
import { requestIntro } from '../components/shell/intro'
import ThemeSwitch from '../components/shell/ThemeSwitch'
import { buttonStyles } from '../components/ui/button'
import { cn } from '../components/ui/cn'

// Lectures the preview can show: how the class did on each question so far,
// what each was on, and the question open now. A different one each time the
// page is opened, in turn, starting again after the last.
type Scenario = {
  lecture: string
  question: string
  answered: number
  of: number
  results: { right: number; topic: string }[]
}

const SCENARIOS: Scenario[] = [
  {
    lecture: 'Week 7, Threat modelling',
    question: 'Which control stops tampering with a signed token?',
    answered: 24,
    of: 28,
    results: [
      { right: 0.82, topic: 'Assets and entry points' },
      { right: 0.68, topic: 'Trust boundaries' },
      { right: 0.9, topic: 'STRIDE categories' },
      { right: 0.46, topic: 'Token signing' },
      { right: 0.74, topic: 'Data flow diagrams' },
      { right: 0.86, topic: 'Spoofing' },
      { right: 0.61, topic: 'Repudiation' },
      { right: 0.93, topic: 'Mitigations' },
    ],
  },
  {
    lecture: 'Week 4, Applied cryptography',
    question: 'Why must a nonce never be reused with the same key?',
    answered: 31,
    of: 35,
    results: [
      { right: 0.88, topic: 'Symmetric keys' },
      { right: 0.72, topic: 'Block cipher modes' },
      { right: 0.91, topic: 'Hash functions' },
      { right: 0.41, topic: 'Key exchange' },
      { right: 0.66, topic: 'Salting passwords' },
      { right: 0.79, topic: 'Digital signatures' },
    ],
  },
  {
    lecture: 'Week 9, Web security',
    question: 'Which header stops another site framing your page?',
    answered: 19,
    of: 22,
    results: [
      { right: 0.84, topic: 'SQL injection' },
      { right: 0.63, topic: 'Cross-site scripting' },
      { right: 0.48, topic: 'CSRF tokens' },
      { right: 0.77, topic: 'Same-origin policy' },
      { right: 0.7, topic: 'Cookie flags' },
      { right: 0.81, topic: 'Session handling' },
      { right: 0.66, topic: 'Content Security Policy' },
    ],
  },
  {
    lecture: 'Week 3, Networks',
    question: 'What does the TCP three-way handshake agree on?',
    answered: 40,
    of: 46,
    results: [
      { right: 0.79, topic: 'OSI layers' },
      { right: 0.58, topic: 'IP addressing' },
      { right: 0.37, topic: 'Subnetting' },
      { right: 0.83, topic: 'DNS lookups' },
      { right: 0.88, topic: 'Ports and services' },
    ],
  },
  {
    lecture: 'Week 11, Databases',
    question: 'Which index helps a query that filters on two columns?',
    answered: 26,
    of: 30,
    results: [
      { right: 0.76, topic: 'Normalisation' },
      { right: 0.81, topic: 'Joins' },
      { right: 0.69, topic: 'Transactions' },
      { right: 0.44, topic: 'Isolation levels' },
      { right: 0.72, topic: 'Indexes' },
      { right: 0.58, topic: 'Query plans' },
      { right: 0.87, topic: 'Constraints' },
      { right: 0.64, topic: 'Deadlocks' },
    ],
  },
]

const PREVIEW_KEY = 'clip_login_preview'

/** The next lecture in turn, remembered per browser. Random when the browser
 * keeps nothing, so a private window still sees some variety. */
function nextScenario(): Scenario {
  let index: number
  try {
    const last = Number.parseInt(window.localStorage.getItem(PREVIEW_KEY) ?? '', 10)
    index = Number.isNaN(last) ? 0 : (last + 1) % SCENARIOS.length
    window.localStorage.setItem(PREVIEW_KEY, String(index))
  } catch {
    index = Math.floor(Math.random() * SCENARIOS.length)
  }
  return SCENARIOS[index]
}

const EASE = [0.16, 1, 0.3, 1] as const

/** What went wrong, in words a student can act on. */
function signInProblem(caught: unknown): string {
  if (!(caught instanceof ApiError)) return 'Could not reach C.L.I.P. Check your connection and try again.'
  if (caught.status === 422) return 'That email address does not look right. Check it and try again.'
  if (caught.status === 401) return 'That email and password do not match an account. Check both and try again.'
  if (caught.status === 429) return 'Too many attempts. Wait a minute, then try again.'
  if (caught.status >= 500) return 'C.L.I.P is having trouble right now. Try again in a moment.'
  return caught.message
}

export default function LoginPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [capsLock, setCapsLock] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const passwordField = useRef<HTMLInputElement>(null)
  const form = useAnimationControls()
  const reduced = useReducedMotion()

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
      setError(signInProblem(caught))
      // A small shake says "no" without a modal; then straight back to the
      // password, which is the field most often wrong.
      if (!reduced) void form.start({ x: [0, -7, 6, -4, 2, 0], transition: { duration: 0.38 } })
      passwordField.current?.select()
    } finally {
      setSubmitting(false)
    }
  }

  function watchCapsLock(event: KeyboardEvent<HTMLInputElement>) {
    setCapsLock(event.getModifierState?.('CapsLock') ?? false)
  }

  const field =
    'mt-1.5 w-full rounded-md border border-input bg-input-background px-3 py-2.5 transition-[border-color,box-shadow] duration-150 hover:border-muted-foreground/50 focus:border-primary focus:shadow-[0_0_0_3px_var(--accent)] focus:outline-none aria-[invalid=true]:border-critical'

  return (
    <main className="grid min-h-screen bg-background lg:grid-cols-[1.1fr_1fr]">
      <Story />

      <section className="relative flex flex-col justify-center px-6 py-12 sm:px-12">
        <div className="absolute right-4 top-4 w-28 sm:right-6 sm:top-6">
          <ThemeSwitch />
        </div>
        <motion.div
          className="mx-auto w-full max-w-sm"
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.45, ease: EASE, delay: 0.1 }}
        >
          <div className="mb-10 lg:hidden">
            <Wordmark />
            <p className="mt-3 max-w-xs text-sm text-muted-foreground">Know how the class is doing while you are still teaching it.</p>
          </div>
          <h2 className="text-2xl font-bold">Sign in</h2>
          <p className="mt-1 text-muted-foreground">With your C.L.I.P account.</p>

          <motion.form onSubmit={submit} animate={form} className="mt-8 space-y-4">
            <label className="block text-sm font-semibold">
              Email
              <input
                type="email"
                required
                autoComplete="username"
                inputMode="email"
                spellCheck={false}
                autoFocus
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                aria-invalid={error ? true : undefined}
                aria-describedby={error ? 'sign-in-error' : undefined}
                className={field}
              />
            </label>

            <div>
              <label htmlFor="password" className="block text-sm font-semibold">
                Password
              </label>
              <div className="relative">
                <input
                  ref={passwordField}
                  id="password"
                  type={showPassword ? 'text' : 'password'}
                  required
                  autoComplete="current-password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  onKeyDown={watchCapsLock}
                  onKeyUp={watchCapsLock}
                  onBlur={() => setCapsLock(false)}
                  aria-invalid={error ? true : undefined}
                  aria-describedby={[error ? 'sign-in-error' : '', capsLock ? 'caps-lock' : ''].join(' ').trim() || undefined}
                  className={cn(field, 'pr-11')}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((value) => !value)}
                  aria-pressed={showPassword}
                  className="absolute right-1 top-[calc(50%+3px)] grid h-9 w-9 -translate-y-1/2 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                >
                  {showPassword ? <EyeOff size={17} aria-hidden /> : <Eye size={17} aria-hidden />}
                  <span className="sr-only">Show password</span>
                </button>
              </div>
              <motion.p
                id="caps-lock"
                initial={false}
                animate={{ height: capsLock ? 'auto' : 0, opacity: capsLock ? 1 : 0 }}
                transition={{ duration: 0.16 }}
                className="overflow-hidden text-sm text-warning"
                aria-live="polite"
              >
                <span className="block pt-1.5">Caps Lock is on.</span>
              </motion.p>
            </div>

            {error && (
              <motion.p
                id="sign-in-error"
                role="alert"
                initial={{ opacity: 0, y: -4 }}
                animate={{ opacity: 1, y: 0 }}
                className="flex items-start gap-2 rounded-md border border-critical/30 bg-critical/10 px-3 py-2 text-sm text-critical"
              >
                <AlertCircle size={16} aria-hidden className="mt-0.5 shrink-0" />
                {error}
              </motion.p>
            )}

            <button type="submit" disabled={submitting} className={cn(buttonStyles(), 'group w-full py-2.5')}>
              {submitting ? (
                <>
                  <LoaderCircle size={16} aria-hidden className="animate-spin" />
                  Signing in…
                </>
              ) : (
                <>
                  Sign in
                  <ArrowRight size={16} aria-hidden className="transition-transform duration-150 group-hover:translate-x-0.5 motion-reduce:group-hover:translate-x-0" />
                </>
              )}
            </button>
          </motion.form>

        </motion.div>
      </section>
    </main>
  )
}

/**
 * The left half on a wide screen: one live lecture, as the lecturer sees it.
 * The headline's last words get the highlighter, then a preview of the live
 * page builds itself: the open question counting its answers in, how the
 * class did on each question so far, and the topic worth going over again.
 * It plays once.
 */
function Story() {
  return (
    <section className="relative hidden flex-col justify-between overflow-hidden border-r border-border bg-card px-14 py-12 lg:flex">
      {/* A faint grid of ruled lines, like the page of a notebook. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-[0.5] [background-image:linear-gradient(to_bottom,var(--border)_1px,transparent_1px)] [background-size:100%_2.25rem] [mask-image:linear-gradient(to_bottom,transparent,black_30%,black_70%,transparent)]"
      />
      {/* Two soft lights behind the preview, in the brand indigo and the highlighter. */}
      <div aria-hidden className="pointer-events-none absolute -bottom-24 -right-24 h-[26rem] w-[26rem] rounded-full bg-primary/15 blur-3xl" />
      <div aria-hidden className="pointer-events-none absolute bottom-40 -left-16 h-56 w-56 rounded-full bg-highlight/20 blur-3xl" />
      <div className="relative">
        <Wordmark />
      </div>

      <div className="relative my-auto pt-10">
        <h1 className="max-w-md text-[2.6rem] font-extrabold leading-[1.12]">
          Know how the class is doing while you are{' '}
          <span className="relative inline-block whitespace-nowrap">
            {/* The highlighter, full letter height, so the words sit on it whole. */}
            <motion.span
              aria-hidden
              className="absolute inset-x-[-0.12em] bottom-[0.02em] top-[0.08em] origin-left rounded-sm bg-highlight"
              initial={{ scaleX: 0 }}
              animate={{ scaleX: 1 }}
              transition={{ delay: 0.45, duration: 0.7, ease: EASE }}
            />
            <span className="relative">still teaching it.</span>
            {/* The same words in ink for the highlighter, uncovered with the
                stroke, so no letter is ever light on yellow or dark on dark. */}
            <motion.span
              aria-hidden
              className="absolute inset-0 text-highlight-foreground"
              initial={{ clipPath: 'inset(0 100% 0 0)' }}
              animate={{ clipPath: 'inset(0 0% 0 0)' }}
              transition={{ delay: 0.45, duration: 0.7, ease: EASE }}
            >
              still teaching it.
            </motion.span>
          </span>
        </h1>
        <p className="mt-4 max-w-md text-lg text-muted-foreground">
          Questions drawn from your slides, answered live, and the topics that tripped the room up, before the lecture ends.
        </p>

        <LivePreview />
      </div>

    </section>
  )
}

/** A picture of the lecturer's live page, labelled so it explains itself. */
function LivePreview() {
  const [scenario] = useState(nextScenario)
  const { lecture, question, answered, of, results } = scenario
  const open = results.length + 1
  const weakest = results.reduce((low, result) => (result.right < low.right ? result : low))
  return (
    <motion.figure
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.8, duration: 0.6, ease: EASE }}
      className="mt-10 max-w-md overflow-hidden rounded-xl border border-border bg-background shadow-[0_24px_60px_-24px_rgba(27,28,43,0.35)]"
    >
      <div aria-hidden>
        <div className="border-b border-border px-4 py-2.5">
          <p className="text-sm font-semibold">{lecture}</p>
        </div>

        {/* The open question. */}
        <div className="border-b border-border px-4 py-3.5">
          <p className="text-xs font-semibold text-muted-foreground">Question {open}, open now</p>
          <p className="mt-1 text-[0.95rem] font-semibold leading-snug">{question}</p>
          <div className="mt-3 flex items-center gap-3">
            <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
              <motion.div
                className="h-full rounded-full bg-primary"
                initial={{ width: 0 }}
                animate={{ width: `${(answered / of) * 100}%` }}
                transition={{ delay: 1.3, duration: 1.4, ease: EASE }}
              />
            </div>
            <p className="shrink-0 text-xs text-muted-foreground">
              <CountUp to={answered} delay={1.3} /> of {of} answered
            </p>
          </div>
        </div>

        {/* How the class did on each question so far. */}
        <div className="px-4 pb-3 pt-3.5">
          <p className="text-xs font-semibold text-muted-foreground">Answered right, by question</p>
          <ol className="mt-3 flex h-20 items-end gap-1.5">
            {results.map((result, index) => {
              const low = result === weakest
              const label = `Q${index + 1}`
              return (
                <li key={label} className="flex h-full flex-1 flex-col items-center gap-1">
                  <div className="flex w-full flex-1 items-end overflow-hidden rounded-[3px] bg-muted">
                    <motion.div
                      className={cn('w-full rounded-[3px]', low ? 'bg-warning' : 'bg-success/85')}
                      initial={{ height: 0 }}
                      animate={{ height: `${result.right * 100}%` }}
                      transition={{ delay: 1.1 + index * 0.06, duration: 0.6, ease: EASE }}
                    />
                  </div>
                  <span className={cn('text-[0.68rem] tabular-nums', low ? 'font-bold text-foreground' : 'text-muted-foreground')}>
                    {label}
                  </span>
                </li>
              )
            })}
            {/* The open question has no result yet. */}
            <li className="flex h-full flex-1 flex-col items-center gap-1">
              <div className="w-full flex-1 rounded-[3px] border border-dashed border-primary/50 bg-primary/5" />
              <span className="text-[0.68rem] font-semibold text-primary">Q{open}</span>
            </li>
          </ol>
        </div>

        {/* The topic the chart points at. */}
        <motion.div
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 2, duration: 0.5, ease: EASE }}
          className="mx-4 mb-4 flex items-center justify-between gap-3 rounded-lg bg-warning/15 px-3 py-2"
        >
          <p className="text-sm">
            <span className="font-semibold">Go over again:</span> {weakest.topic}
          </p>
          <p className="shrink-0 text-xs font-semibold tabular-nums">{Math.round(weakest.right * 100)}% right</p>
        </motion.div>
      </div>
      <figcaption className="sr-only">
        A live lecture in C.L.I.P, {lecture}: question {open} is open with {answered} of {of} students answered, and{' '}
        {weakest.topic} is the topic the class found hardest so far.
      </figcaption>
    </motion.figure>
  )
}

function CountUp({ to, delay }: { to: number; delay: number }) {
  const node = useRef<HTMLSpanElement>(null)
  const reduced = useReducedMotion()
  useEffect(() => {
    if (!node.current) return
    if (reduced) {
      node.current.textContent = String(to)
      return
    }
    const controls = animate(0, to, {
      delay,
      duration: 1.4,
      ease: EASE,
      onUpdate: (value) => {
        if (node.current) node.current.textContent = String(Math.round(value))
      },
    })
    return () => controls.stop()
  }, [to, delay, reduced])
  return (
    <span ref={node} className="font-semibold text-foreground tabular-nums">
      0
    </span>
  )
}
