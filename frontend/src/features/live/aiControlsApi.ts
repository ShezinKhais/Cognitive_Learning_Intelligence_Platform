import { apiAuthenticatedGet, apiAuthenticatedRequest } from '../../api'
import { aiControlsPath, type AiControls, type AiControlsView } from './aiControls'

export function getAiControls(sessionId: string): Promise<AiControlsView> {
  return apiAuthenticatedGet<AiControlsView>(aiControlsPath(sessionId))
}

export function saveAiControls(
  sessionId: string,
  controls: AiControls,
  applyToCourse: boolean,
): Promise<AiControlsView> {
  return apiAuthenticatedRequest<AiControlsView>(aiControlsPath(sessionId), {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...controls, apply_to_course: applyToCourse }),
  })
}
