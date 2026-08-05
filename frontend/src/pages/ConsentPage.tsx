import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { useNavigate } from 'react-router'

import {
  ApiError,
  getCurrentUser,
  recordConsent,
  type CurrentUser,
} from '../api'

export default function ConsentPage() {
  const navigate = useNavigate()

  const [user, setUser] = useState<CurrentUser | null>(null)
  const [terms, setTerms] = useState(false)
  const [monitoring, setMonitoring] = useState(false)
  const [camera, setCamera] = useState(false)
  const [microphone, setMicrophone] = useState(false)

  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    getCurrentUser()
      .then((currentUser) => {
        if (cancelled) return

        setUser(currentUser)
        setTerms(currentUser.consents.includes('terms'))
        setMonitoring(
          currentUser.consents.includes('engagement_monitoring'),
        )
        setCamera(currentUser.consents.includes('camera'))
        setMicrophone(currentUser.consents.includes('microphone'))
      })
      .catch((caught) => {
        if (cancelled) return

        if (caught instanceof ApiError && caught.status === 401) {
          navigate('/login', { replace: true })
          return
        }

        setError(
          caught instanceof Error
            ? caught.message
            : 'Could not load your account.',
        )
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [navigate])

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()

    if (!user) {
      setError('Could not verify your account.')
      return
    }

    if (!terms) {
      setError('You must accept the terms before continuing.')
      return
    }

    setSaving(true)
    setError(null)

    try {
      // All roles accept the platform terms.
      await recordConsent('terms', true)

      // Only students provide engagement, camera and microphone consent.
      if (user.role === 'student') {
        await recordConsent('engagement_monitoring', monitoring)
        await recordConsent('camera', camera)
        await recordConsent('microphone', microphone)
      }

      if (user.role === 'admin') {
        navigate('/admin', { replace: true })
      } else {
        navigate('/', { replace: true })
      }
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
    return (
      <main className="min-h-screen grid place-items-center">
        Loading your account…
      </main>
    )
  }

  if (!user) {
    return (
      <main className="min-h-screen grid place-items-center p-8">
        <p role="alert" className="text-critical">
          {error ?? 'Could not load your account.'}
        </p>
      </main>
    )
  }

  const isStudent = user.role === 'student'

  return (
    <main className="min-h-screen grid place-items-center p-8">
      <form
        onSubmit={submit}
        className="w-full max-w-xl rounded-xl border border-border bg-card p-6"
      >
        <h1 className="text-xl font-bold">
          Terms and privacy
        </h1>

        {isStudent ? (
          <p className="mt-2 text-sm text-muted-foreground">
            Engagement monitoring, camera indicators and microphone
            indicators are optional and can be accepted separately.
          </p>
        ) : (
          <p className="mt-2 text-sm text-muted-foreground">
            Your role only requires acceptance of the C.L.I.P terms and
            privacy notice. Student monitoring permissions do not apply to
            your account.
          </p>
        )}

        <Choice
          label="I accept the C.L.I.P terms and privacy notice"
          checked={terms}
          onChange={setTerms}
        />

        {isStudent && (
          <>
            <Choice
              label="Allow engagement monitoring"
              checked={monitoring}
              onChange={setMonitoring}
            />

            <Choice
              label="Allow camera-derived indicators"
              checked={camera}
              onChange={setCamera}
            />

            <Choice
              label="Allow microphone voice-activity indicators"
              checked={microphone}
              onChange={setMicrophone}
            />
          </>
        )}

        {error && (
          <p role="alert" className="mt-4 text-sm text-critical">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={saving}
          className="mt-6 rounded-lg bg-primary px-4 py-2 font-medium text-primary-foreground disabled:opacity-50"
        >
          {saving ? 'Saving…' : 'Accept and continue'}
        </button>
      </form>
    </main>
  )
}

function Choice({
  label,
  checked,
  onChange,
}: {
  label: string
  checked: boolean
  onChange: (checked: boolean) => void
}) {
  return (
    <label className="mt-4 flex items-start gap-3 rounded-lg bg-muted p-3 text-sm">
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span>{label}</span>
    </label>
  )
}