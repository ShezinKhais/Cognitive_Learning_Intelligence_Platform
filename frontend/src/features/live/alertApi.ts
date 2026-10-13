import {
  apiAuthenticatedGet,
  apiAuthenticatedRequest,
} from '../../api'

export type PersistedAlertStatus =
  | 'open'
  | 'acknowledged'

export interface PersistedAlert {
  alert_id: string
  session_id: string
  question_id: string | null
  kind: string
  topic: string | null
  message: string
  reason: string
  confidence: number
  explanation: string
  explanation_source:
    | 'ai'
    | 'fallback'
  confidence_reasons: string[]
  recommendation: string
  status: PersistedAlertStatus
  raised_at: string
  acknowledged_by: string | null
  acknowledged_at: string | null
  respondents: number | null
  threshold: number | null
  correct_ratio: number | null
}

export function getOpenSessionAlerts(
  sessionId: string,
): Promise<PersistedAlert[]> {
  return apiAuthenticatedGet<
    PersistedAlert[]
  >(
    `/sessions/${encodeURIComponent(
      sessionId,
    )}/alerts?status=open`,
  )
}

export function acknowledgeSessionAlert(
  sessionId: string,
  alertId: string,
): Promise<PersistedAlert> {
  return apiAuthenticatedRequest<
    PersistedAlert
  >(
    `/sessions/${encodeURIComponent(
      sessionId,
    )}/alerts/${encodeURIComponent(
      alertId,
    )}/acknowledge`,
    {
      method: 'POST',
    },
  )
}