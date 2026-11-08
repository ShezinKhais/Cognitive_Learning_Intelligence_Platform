import { apiAuthenticatedGet, apiAuthenticatedRequest } from '../../api'
import { teamsUpdatesPath, type TeamsUpdates } from '../../teams/lecturerUpdates'

export function getTeamsUpdates(sessionId: string): Promise<TeamsUpdates> {
  return apiAuthenticatedGet<TeamsUpdates>(teamsUpdatesPath(sessionId))
}

export function setTeamsUpdatesMuted(sessionId: string, muted: boolean): Promise<TeamsUpdates> {
  return apiAuthenticatedRequest<TeamsUpdates>(teamsUpdatesPath(sessionId), {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ muted }),
  })
}
