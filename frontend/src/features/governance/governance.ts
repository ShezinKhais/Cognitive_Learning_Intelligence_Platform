export type DeletionTargetType =
  | 'session'
  | 'student'

export type DeletionRequestStatus =
  | 'requested'
  | 'approved'
  | 'rejected'
  | 'executed'

export interface DeletionRequestCreate {
  target_type: DeletionTargetType
  target_id: string
  reason: string | null
}

export interface DeletionRequest {
  request_id: string
  target_type: DeletionTargetType
  target_id: string
  status: DeletionRequestStatus
  reason: string | null
  requested_by: string
  requested_at: string
  decided_by: string | null
  decided_at: string | null
  executed_by: string | null
  executed_at: string | null
  outcome: Record<
    string,
    unknown
  > | null
}

export interface AuditEntry {
  log_id: string
  user_id: string | null
  action_type: string
  timestamp: string
  ip_address: string | null
  target_type: string | null
  target_id: string | null
  details: Record<
    string,
    unknown
  > | null
}

export interface RetentionReport {
  cutoff: string
  dry_run: boolean
  retention_days: number
  sessions: number
  answers: number
  roster_syncs: number
}

export interface AuditLogFilters {
  action_type?: string
  user_id?: string
  target_type?: string
  target_id?: string
  since?: string
  until?: string
}

export function deletionStatusLabel(
  status: DeletionRequestStatus,
): string {
  if (status === 'requested') {
    return 'Requested'
  }

  if (status === 'approved') {
    return 'Approved'
  }

  if (status === 'rejected') {
    return 'Rejected'
  }

  return 'Executed'
}

export function deletionTargetLabel(
  targetType: DeletionTargetType,
): string {
  if (targetType === 'session') {
    return 'Session'
  }

  return 'Student'
}

export function canApproveDeletion(
  request: DeletionRequest,
  currentAdminId: string,
): boolean {
  return (
    request.status === 'requested' &&
    request.requested_by !==
      currentAdminId
  )
}

export function canRejectDeletion(
  request: DeletionRequest,
): boolean {
  return (
    request.status === 'requested'
  )
}

export function canExecuteDeletion(
  request: DeletionRequest,
): boolean {
  return (
    request.status === 'approved' &&
    request.target_type === 'session'
  )
}
