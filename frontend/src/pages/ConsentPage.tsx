import { useEffect, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { useLocation, useNavigate } from 'react-router'
import { motion } from 'motion/react'
import { Activity, Camera, Check, Mic, type LucideIcon } from 'lucide-react'

import {
  ApiError,
  getCurrentUser,
  recordConsent,
  type CurrentUser,
} from '../api'
import { intendedPathForRole } from '../authRouting'
import { Wordmark } from '../components/brand/ClipMark'
import PageLoader from '../components/brand/PageLoader'
import { buttonStyles } from '../components/ui/button'
import { cn } from '../components/ui/cn'
import { ProblemState } from '../components/ui/ProblemState'
import { problemArt } from '../components/ui/problem'

export default function ConsentPage() {
  const navigate = useNavigate()
  const location = useLocation()

  const [user, setUser] = useState<CurrentUser | null>(null)

  const [terms, setTerms] = useState(false)
  const [monitoring, setMonitoring] = useState(false)
  const [camera, setCamera] = useState(false)
  const [microphone, setMicrophone] = useState(false)

  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [loadCause, setLoadCause] = useState<unknown>(null)

  useEffect(() => {
    let cancelled = false

    getCurrentUser()
      .then((currentUser) => {
        if (cancelled) {
          return
        }

        setUser(currentUser)

        setTerms(currentUser.consents.includes('terms'))

        if (currentUser.role === 'student') {
          setMonitoring(
            currentUser.consents.includes(
              'engagement_monitoring',
            ),
          )
          setCamera(
            currentUser.consents.includes('camera'),
          )
          setMicrophone(
            currentUser.consents.includes('microphone'),
          )
        }
      })
      .catch((caught) => {
        if (cancelled) {
          return
        }

        if (
          caught instanceof ApiError &&
          caught.status === 401
        ) {
          navigate('/login', { replace: true })
          return
        }

        setLoadCause(caught)
        setError(
          caught instanceof Error
            ? caught.message
            : 'Could not load your account.',
        )
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false)
        }
      })

    return () => {
      cancelled = true
    }
  }, [navigate])

  async function submit(event: FormEvent) {
    event.preventDefault()

    if (!user) {
      setError('Could not verify your account.')
      return
    }

    if (!terms) {
      setError(
        'You must accept the terms before continuing.',
      )
      return
    }

    setSaving(true)
    setError(null)

    try {
      await recordConsent('terms', true)

      if (user.role === 'student') {
        await recordConsent(
          'engagement_monitoring',
          monitoring,
        )
        await recordConsent('camera', camera)
        await recordConsent('microphone', microphone)
      }

      const requestedPath = (
        location.state as { from?: string } | null
      )?.from

      navigate(
        intendedPathForRole(user.role, requestedPath),
        { replace: true },
      )
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.message
          : 'Could not save your choices.',
      )
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return <PageLoader label="Loading your account" />
  }

  if (!user) {
    return (
      <Frame>
        <ProblemState art={problemArt(loadCause)} title="Your account could not be loaded">
          {error ?? 'Could not load your account.'}
        </ProblemState>
      </Frame>
    )
  }

  const isStudent = user.role === 'student'
  const firstName = user.full_name.split(' ')[0]

  return (
    <Frame>
      <form onSubmit={submit}>
        <h1 className="text-[1.75rem] font-bold leading-tight">Before you start, {firstName}</h1>
        <p className="mt-2 text-muted-foreground">
          {isStudent
            ? 'Accept the terms to continue. Everything under them is optional, and each one is separate.'
            : 'Accept the terms to continue. The student permissions do not apply to your account.'}
        </p>

        <label
          className={cn(
            'mt-6 flex cursor-pointer items-start gap-3 rounded-lg border bg-card px-4 py-4 transition-colors',
            terms ? 'border-primary' : 'border-border hover:border-input',
          )}
        >
          <input
            type="checkbox"
            checked={terms}
            onChange={(event) => setTerms(event.target.checked)}
            className="peer sr-only"
          />
          <span
            className={cn(
              'mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded border transition-colors peer-focus-visible:ring-2 peer-focus-visible:ring-ring',
              terms ? 'border-primary bg-primary text-primary-foreground' : 'border-input bg-input-background',
            )}
            aria-hidden
          >
            {terms && <Check size={14} strokeWidth={3} />}
          </span>
          <span>
            <span className="block font-semibold">I accept the C.L.I.P terms and privacy notice</span>
            <span className="block text-sm text-muted-foreground">Required</span>
          </span>
        </label>

        {isStudent && (
          <fieldset className="mt-6">
            <legend className="font-semibold">Optional, for engagement estimates</legend>
            <p className="mt-0.5 text-sm text-muted-foreground">
              Your lecturer sees an estimate, never video or sound. Leaving these off is never counted against you.
            </p>
            <div className="mt-3 divide-y divide-border rounded-lg border border-border bg-card">
              <Permission
                icon={Activity}
                label="Engagement monitoring"
                detail="Estimates from how you take part, such as answering checkpoints."
                checked={monitoring}
                onChange={setMonitoring}
              />
              <Permission
                icon={Camera}
                label="Camera indicators"
                detail="Whether a face is in view, worked out in your browser. The video is not sent."
                checked={camera}
                onChange={setCamera}
              />
              <Permission
                icon={Mic}
                label="Microphone indicators"
                detail="Whether you are speaking, worked out in your browser. The sound is not sent."
                checked={microphone}
                onChange={setMicrophone}
              />
            </div>
          </fieldset>
        )}

        {error && (
          <p role="alert" className="mt-4 text-sm text-critical">
            {error}
          </p>
        )}

        <button type="submit" disabled={saving || !terms} className={cn(buttonStyles(), 'mt-6 w-full py-2.5')}>
          {saving ? 'Saving…' : 'Continue'}
        </button>
      </form>
    </Frame>
  )
}

function Frame({ children }: { children: ReactNode }) {
  return (
    <main className="min-h-screen bg-background px-4 py-10 sm:py-16">
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
        className="mx-auto w-full max-w-lg"
      >
        <div className="mb-8">
          <Wordmark />
        </div>
        {children}
      </motion.div>
    </main>
  )
}

function Permission({
  icon: Icon,
  label,
  detail,
  checked,
  onChange,
}: {
  icon: LucideIcon
  label: string
  detail: string
  checked: boolean
  onChange: (checked: boolean) => void
}) {
  return (
    <label className="flex cursor-pointer items-start gap-3 px-4 py-3.5">
      <Icon size={18} aria-hidden className="mt-0.5 shrink-0 text-muted-foreground" />
      <span className="min-w-0 flex-1">
        <span className="block font-semibold">{label}</span>
        <span className="block text-sm text-muted-foreground">{detail}</span>
      </span>
      <input
        type="checkbox"
        role="switch"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        className="peer sr-only"
      />
      <span
        aria-hidden
        className={cn(
          'relative mt-0.5 h-6 w-10 shrink-0 rounded-full transition-colors peer-focus-visible:ring-2 peer-focus-visible:ring-ring',
          checked ? 'bg-primary' : 'bg-muted-foreground/30',
        )}
      >
        <motion.span
          className="absolute top-0.5 h-5 w-5 rounded-full bg-card shadow-sm"
          initial={false}
          animate={{ left: checked ? 18 : 2 }}
          transition={{ type: 'spring', stiffness: 500, damping: 32 }}
        />
      </span>
    </label>
  )
}
