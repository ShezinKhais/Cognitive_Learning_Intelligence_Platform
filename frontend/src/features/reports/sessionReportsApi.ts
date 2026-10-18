import {
  ApiError,
  apiAuthenticatedGet,
  apiAuthenticatedRequest,
  authenticatedFetch,
} from '../../api.ts'

import type {
  ReportJob,
} from './sessionReports'

export interface ReportPdfDownload {
  blob: Blob
  filename: string
}

export function requestSessionReport(
  sessionId: string,
): Promise<ReportJob> {
  return apiAuthenticatedRequest<ReportJob>(
    `/sessions/${encodeURIComponent(
      sessionId,
    )}/reports`,
    {
      method: 'POST',
    },
  )
}

export function getSessionReport(
  reportId: string,
): Promise<ReportJob> {
  return apiAuthenticatedGet<ReportJob>(
    `/reports/${encodeURIComponent(
      reportId,
    )}`,
  )
}

function filenameFromDisposition(
  value: string | null,
): string {
  if (!value) {
    return 'clip-session-report.pdf'
  }

  const match =
    /filename="([^"]+)"/i.exec(
      value,
    )

  return (
    match?.[1] ??
    'clip-session-report.pdf'
  )
}

async function pdfError(
  response: Response,
): Promise<ApiError> {
  let code = 'HTTP_ERROR'
  let message =
    `HTTP ${response.status}`

  try {
    const body =
      await response.json()

    code =
      body?.error?.code ??
      code

    message =
      body?.error?.message ??
      message
  } catch {
    // A non-JSON error uses the safe
    // HTTP fallback above.
  }

  return new ApiError(
    response.status,
    code,
    message,
  )
}

export async function downloadSessionReportPdf(
  reportId: string,
): Promise<ReportPdfDownload> {
  const response =
    await authenticatedFetch(
      `/reports/${encodeURIComponent(
        reportId,
      )}/pdf`,
    )

  if (!response.ok) {
    throw await pdfError(response)
  }

  return {
    blob:
      await response.blob(),
    filename:
      filenameFromDisposition(
        response.headers.get(
          'Content-Disposition',
        ),
      ),
  }
}
