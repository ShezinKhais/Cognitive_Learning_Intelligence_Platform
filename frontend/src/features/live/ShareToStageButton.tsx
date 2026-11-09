import { useState } from 'react'
import { MonitorUp } from 'lucide-react'

import { buttonStyles } from '../../components/ui/button'
import { STAGE_MESSAGES, shareSessionToStage, type StageShareResult } from '../../teams/stage'
import { teamsStageHost } from '../../teams/stageHost'
import { useTeams } from '../../teams/TeamsProvider'

/**
 * Puts the class on the Teams meeting stage, so everyone sees it large
 * instead of only in their side panel. Shown only inside a Teams meeting.
 */
export default function ShareToStageButton({ sessionId }: { sessionId: string }) {
  const teams = useTeams()
  const [working, setWorking] = useState(false)
  const [result, setResult] = useState<StageShareResult | null>(null)

  if (teams.host !== 'teams') {
    return null
  }

  async function share(): Promise<void> {
    setWorking(true)
    setResult(null)
    setResult(await shareSessionToStage(teamsStageHost, window.location.origin, sessionId))
    setWorking(false)
  }

  return (
    <div>
      <button
        type="button"
        className={buttonStyles({ intent: 'secondary', className: 'w-full' })}
        disabled={working}
        onClick={() => void share()}
      >
        <MonitorUp size={15} aria-hidden />
        {working ? 'Sharing…' : 'Share to the meeting stage'}
      </button>
      {result && (
        <p role="status" className="mt-2 text-xs text-muted-foreground">
          {STAGE_MESSAGES[result]}
        </p>
      )}
    </div>
  )
}
