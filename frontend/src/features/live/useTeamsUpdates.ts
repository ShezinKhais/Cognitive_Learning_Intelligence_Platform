import { useCallback, useEffect, useState } from 'react'

import type { TeamsUpdates } from '../../teams/lecturerUpdates'
import { getTeamsUpdates, setTeamsUpdatesMuted } from './teamsUpdatesApi'

// Updates arrive while the lecturer teaches, so the list is read again.
const REFRESH_MS = 15_000

export function useTeamsUpdates(sessionId: string) {
  const [updates, setUpdates] = useState<TeamsUpdates | null>(null)
  const [failed, setFailed] = useState(false)
  const [saving, setSaving] = useState(false)

  const load = useCallback(
    () =>
      getTeamsUpdates(sessionId).then(
        (found) => {
          setUpdates(found)
          setFailed(false)
        },
        () => setFailed(true),
      ),
    [sessionId],
  )

  useEffect(() => {
    void load()
    const timer = window.setInterval(() => void load(), REFRESH_MS)
    return () => window.clearInterval(timer)
  }, [load])

  const setMuted = useCallback(
    (muted: boolean) => {
      setSaving(true)
      setTeamsUpdatesMuted(sessionId, muted).then(
        (found) => {
          setUpdates(found)
          setFailed(false)
          setSaving(false)
        },
        () => {
          setFailed(true)
          setSaving(false)
        },
      )
    },
    [sessionId],
  )

  return { updates, failed, saving, setMuted, reload: load }
}
