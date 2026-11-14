import { apiAuthenticatedRequest, type CurrentUser } from '../../api'

/** A hung verification must not leave a previously authorized device running. */
export async function readCaptureConsent(): Promise<CurrentUser> {
  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), 5000)
  try {
    return await apiAuthenticatedRequest<CurrentUser>('/auth/me', { cache: 'no-store', signal: controller.signal })
  } finally { window.clearTimeout(timeout) }
}
