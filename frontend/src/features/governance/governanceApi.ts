import {
  apiAuthenticatedGet,
  apiAuthenticatedRequest,
  type Page,
} from '../../api'

import type {
  AuditEntry,
  AuditLogFilters,
  DeletionRequest,
  DeletionRequestCreate,
  DeletionRequestStatus,
  RetentionReport,
} from './governance'

function queryString(
  values: Record<
    string,
    string | number | undefined
  >,
): string {
  const params =
    new URLSearchParams()

  for (
    const [key, value] of
    Object.entries(values)
  ) {
    if (
      value === undefined ||
      value === ''
    ) {
      continue
    }

    params.set(
      key,
      String(value),
    )
  }

  const encoded =
    params.toString()

  return encoded
    ? `?${encoded}`
    : ''
}

export function listAuditLog(
  filters: AuditLogFilters = {},
  limit = 50,
  offset = 0,
): Promise<Page<AuditEntry>> {
  return apiAuthenticatedGet<
    Page<AuditEntry>
  >(
    `/governance/audit-log${queryString(
      {
        ...filters,
        limit,
        offset,
      },
    )}`,
  )
}

export function listDeletionRequests(
  status?: DeletionRequestStatus,
  limit = 50,
  offset = 0,
): Promise<
  Page<DeletionRequest>
> {
  return apiAuthenticatedGet<
    Page<DeletionRequest>
  >(
    `/governance/deletion-requests${queryString(
      {
        status,
        limit,
        offset,
      },
    )}`,
  )
}

export function createDeletionRequest(
  payload: DeletionRequestCreate,
): Promise<DeletionRequest> {
  return apiAuthenticatedRequest<
    DeletionRequest
  >(
    '/governance/deletion-requests',
    {
      method: 'POST',
      body:
        JSON.stringify(payload),
    },
  )
}

export function approveDeletionRequest(
  requestId: string,
): Promise<DeletionRequest> {
  return apiAuthenticatedRequest<
    DeletionRequest
  >(
    `/governance/deletion-requests/${encodeURIComponent(
      requestId,
    )}/approve`,
    {
      method: 'POST',
    },
  )
}

export function rejectDeletionRequest(
  requestId: string,
): Promise<DeletionRequest> {
  return apiAuthenticatedRequest<
    DeletionRequest
  >(
    `/governance/deletion-requests/${encodeURIComponent(
      requestId,
    )}/reject`,
    {
      method: 'POST',
    },
  )
}

export function executeDeletionRequest(
  requestId: string,
): Promise<DeletionRequest> {
  return apiAuthenticatedRequest<
    DeletionRequest
  >(
    `/governance/deletion-requests/${encodeURIComponent(
      requestId,
    )}/execute`,
    {
      method: 'POST',
    },
  )
}

export function previewRetention():
Promise<RetentionReport> {
  return apiAuthenticatedGet<
    RetentionReport
  >(
    '/governance/retention/preview',
  )
}

export function runRetention():
Promise<RetentionReport> {
  return apiAuthenticatedRequest<
    RetentionReport
  >(
    '/governance/retention/run',
    {
      method: 'POST',
      body:
        JSON.stringify({
          confirm: true,
        }),
    },
  )
}