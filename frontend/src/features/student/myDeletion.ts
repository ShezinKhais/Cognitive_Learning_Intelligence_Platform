export type DeletionStatus = 'requested' | 'approved' | 'rejected' | 'executed'

export interface MyDeletionRequest {
  request_id: string
  status: DeletionStatus
  requested_at: string
  decided_at: string | null
  executed_at: string | null
}

/** A request still waiting for, or approved by, an administrator blocks a new one. */
export function isOpen(request: MyDeletionRequest | null): boolean {
  return request?.status === 'requested' || request?.status === 'approved'
}
