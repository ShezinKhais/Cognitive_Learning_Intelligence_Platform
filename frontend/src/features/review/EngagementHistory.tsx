import { useEffect, useState } from 'react'

import { apiAuthenticatedGet } from '../../api'
import { Panel, Tag } from '../../components/ui/primitives'

type Availability = 'available' | 'none_recorded' | 'not_consented'

interface ClassEngagement {
  session_id: string
  title: string
  course_code: string
  ended_at: string | null
  participation: { joined: boolean; checkpoints: number; answered: number; missed: number }
  readings: {
    camera: Availability
    camera_windows: number | null
    microphone: Availability
    microphone_windows: number | null
  }
}

interface History {
  classes: ClassEngagement[]
  total: number
  explanation: string
}

function reading(state: Availability, windows: number | null): string {
  if (state === 'not_consented') return 'Not agreed to'
  if (state === 'none_recorded' || !windows) return 'None recorded'
  return `${windows} ${windows === 1 ? 'minute' : 'minutes'}`
}

/** What each finished class recorded, for the student (#243). No score:
 * answers are counted, and readings say only whether they exist. */
export default function EngagementHistory() {
  const [history, setHistory] = useState<History | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let current = true
    apiAuthenticatedGet<History>('/me/engagement-history?limit=20').then(
      (found) => current && setHistory(found),
      () => current && setFailed(true),
    )
    return () => {
      current = false
    }
  }, [])

  if (failed) return null
  if (!history || history.classes.length === 0) return null

  return (
    <Panel title="Class by class" description={history.explanation} className="mt-6">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <caption className="sr-only">Your participation and device readings in each finished class</caption>
          <thead className="text-left text-muted-foreground">
            <tr>
              <th scope="col" className="py-2 pr-4 font-medium">Class</th>
              <th scope="col" className="py-2 pr-4 font-medium">Answered</th>
              <th scope="col" className="py-2 pr-4 font-medium">Camera</th>
              <th scope="col" className="py-2 font-medium">Microphone</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {history.classes.map((item) => (
              <tr key={item.session_id}>
                <th scope="row" className="py-2 pr-4 text-left font-medium">
                  <span className="block">{item.title}</span>
                  <span className="text-xs font-normal text-muted-foreground">{item.course_code}</span>
                </th>
                <td className="py-2 pr-4">
                  {item.participation.checkpoints === 0 ? (
                    <span className="text-muted-foreground">No checkpoints</span>
                  ) : (
                    <>
                      {item.participation.answered} of {item.participation.checkpoints}
                      {!item.participation.joined && <span className="ml-2"><Tag>Not joined</Tag></span>}
                    </>
                  )}
                </td>
                <td className="py-2 pr-4 text-muted-foreground">
                  {reading(item.readings.camera, item.readings.camera_windows)}
                </td>
                <td className="py-2 text-muted-foreground">
                  {reading(item.readings.microphone, item.readings.microphone_windows)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  )
}
