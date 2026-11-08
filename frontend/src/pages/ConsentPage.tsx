import { useEffect, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { Link, useLocation, useNavigate } from 'react-router'
import { motion } from 'motion/react'
import { Activity, Camera, Check, Mic, type LucideIcon } from 'lucide-react'

import {
  ApiError,
  getCurrentUser,
  recordConsent,
  type CurrentUser,
} from '../api'
import { intendedPathForRole, STUDENT_DATA_PATH } from '../authRouting'
import { Wordmark } from '../components/brand/ClipMark'
import PageLoader from '../components/brand/PageLoader'
import { buttonStyles } from '../components/ui/button'
import { cn } from '../components/ui/cn'
import { ProblemState } from '../components/ui/ProblemState'
import { problemArt } from '../components/ui/problem'
import { choicesToSave } from '../features/student/monitoringChoices'

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
        const saved = choicesToSave({ monitoring, camera, microphone })
        await recordConsent('engagement_monitoring', saved.monitoring)
        await recordConsent('camera', saved.camera)
        await recordConsent('microphone', saved.microphone)
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
        <p className="mt-2 text-sm text-muted-foreground">
          Read the{' '}
          <a href="/terms" target="_blank" rel="noopener" className="font-semibold text-primary underline underline-offset-2">
            terms of use
          </a>{' '}
          and the{' '}
          <a href="/privacy" target="_blank" rel="noopener" className="font-semibold text-primary underline underline-offset-2">
            privacy notice
          </a>{' '}
          (open in a new tab).
        </p>

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
                detail="Estimates from how you take part, such as answering checkpoints. Turn this on to choose the camera and microphone indicators."
                checked={monitoring}
                onChange={setMonitoring}
              />
              <Permission
                icon={Camera}
                label="Camera indicators"
                detail="Whether a face is in view, worked out in your browser. The video is not sent."
                checked={monitoring && camera}
                onChange={setCamera}
                disabled={!monitoring}
                nested
              />
              <Permission
                icon={Mic}
                label="Microphone indicators"
                detail="Whether you are speaking, worked out in your browser. The sound is not sent."
                checked={monitoring && microphone}
                onChange={setMicrophone}
                disabled={!monitoring}
                nested
              />
            </div>
            <p className="mt-3 text-sm text-muted-foreground">
              The indicators you turn on here start by themselves when you join a live class. Your browser asks for
              permission the first time. You can turn either off during a class, or change your choice here, at any
              time and still take part in everything.
            </p>
            <p className="mt-2 text-sm text-muted-foreground">
              These indicators are separate from your camera and microphone in Microsoft Teams, which Teams handles under
              its own privacy terms.
            </p>
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
      {isStudent && (
        <p className="mt-4 text-sm text-muted-foreground">
          You can still download your data or request erasure without accepting the terms.{' '}
          <Link to={STUDENT_DATA_PATH} className="font-semibold underline">
            Open My data
          </Link>
        </p>
      )}
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
  disabled = false,
  nested = false,
}: {
  icon: LucideIcon
  label: string
  detail: string
  checked: boolean
  onChange: (checked: boolean) => void
  disabled?: boolean
  nested?: boolean
}) {
  return (
    <label
      className={cn(
        'flex items-start gap-3 py-3.5 pr-4',
        nested ? 'pl-10' : 'pl-4',
        disabled ? 'cursor-not-allowed opacity-55' : 'cursor-pointer',
      )}
    >
      <Icon size={18} aria-hidden className="mt-0.5 shrink-0 text-muted-foreground" />
      <span className="min-w-0 flex-1">
        <span className="block font-semibold">{label}</span>
        <span className="block text-sm text-muted-foreground">{detail}</span>
      </span>
      <input
        type="checkbox"
        role="switch"
        checked={checked}
        disabled={disabled}
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
