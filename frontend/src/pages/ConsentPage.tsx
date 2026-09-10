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

      navigate(
        user.role === 'admin' ? '/admin' : '/',
        {
          replace: true,
        },
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
    return (
      <main className="mx-auto max-w-2xl px-6 py-12">
        <p>Loading your account...</p>
      </main>
    )
  }

  if (!user) {
    return (
      <main className="mx-auto max-w-2xl px-6 py-12">
        <p
          role="alert"
          className="text-critical"
        >
          {error ?? 'Could not load your account.'}
        </p>
      </main>
    )
  }

  const isStudent = user.role === 'student'

  return (
    <main className="mx-auto max-w-2xl px-6 py-12">
      <form
        onSubmit={submit}
        className="rounded-xl border border-border bg-card p-6 shadow-sm"
      >
        <h1 className="text-2xl font-semibold">
          Terms and privacy
        </h1>

        {isStudent ? (
          <p className="mt-2 text-sm text-muted-foreground">
            Engagement monitoring, camera indicators and
            microphone indicators are optional. You can choose
            each permission separately.
          </p>
        ) : (
          <p className="mt-2 text-sm text-muted-foreground">
            Your role only requires acceptance of the C.L.I.P
            terms and privacy notice. Student monitoring
            permissions do not apply to your account.
          </p>
        )}

        <div className="mt-6 space-y-4">
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
        </div>

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
          disabled={saving}
          className="mt-6 rounded-lg bg-primary px-4 py-2 font-medium text-primary-foreground disabled:opacity-50"
        >
          {saving ? 'Saving...' : 'Accept and continue'}
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
    <label className="flex items-start gap-3">
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) =>
          onChange(event.target.checked)
        }
        className="mt-1"
      />

      <span>{label}</span>
    </label>
  )
}