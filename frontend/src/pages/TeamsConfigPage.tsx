import { pages } from '@microsoft/teams-js'
import { useEffect, useState } from 'react'

import { meetingTabConfiguration } from '../teams/configuration'
import { useTeams } from '../teams/TeamsProvider'

export default function TeamsConfigPage() {
  const teams = useTeams()
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (teams.status !== 'ready' || teams.host !== 'teams') return

    pages.config.registerOnSaveHandler((saveEvent) => {
      void pages.config
        .setConfig(meetingTabConfiguration(window.location.origin))
        .then(() => saveEvent.notifySuccess())
        .catch((caught: unknown) => {
          const message = caught instanceof Error
            ? caught.message
            : 'The meeting tab could not be configured.'
          setError(message)
          saveEvent.notifyFailure(message)
        })
    })

    try {
      pages.config.setValidityState(true)
    } catch (caught: unknown) {
      setError(
        caught instanceof Error
          ? caught.message
          : 'Microsoft Teams could not enable this configuration.',
      )
    }
  }, [teams.host, teams.status])

  if (teams.status === 'initializing') {
    return <ConfigStatus title="Preparing C.L.I.P" />
  }

  if (teams.status === 'error' || teams.host !== 'teams') {
    return (
      <ConfigStatus
        title="Open this page from Microsoft Teams"
        message={teams.error ?? 'Meeting-tab configuration is available only inside Teams.'}
        isError
      />
    )
  }

  return (
    <ConfigStatus
      title={error ? 'C.L.I.P could not be added' : 'Add C.L.I.P to this meeting'}
      message={error ?? 'Select Save to make the student side panel available in this meeting.'}
      isError={Boolean(error)}
    />
  )
}

function ConfigStatus({
  title,
  message,
  isError = false,
}: {
  title: string
  message?: string
  isError?: boolean
}) {
  return (
    <main className="grid min-h-screen place-items-center bg-background p-6">
      <section
        role={isError ? 'alert' : 'status'}
        className="w-full max-w-md rounded-xl border border-border bg-card p-6"
      >
        <h1 className={`text-xl font-semibold ${isError ? 'text-critical' : ''}`}>
          {title}
        </h1>
        {message && <p className="mt-2 text-sm text-muted-foreground">{message}</p>}
      </section>
    </main>
  )
}
