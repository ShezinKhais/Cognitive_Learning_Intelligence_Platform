import { getAccessToken, refreshAccessToken } from '../../api'

// A socket may outlive its credential, or race an HTTP refresh. Reuse a
// newer credential before requesting a refresh. The hook bounds this to one
// recovery attempt until the server accepts the handshake with READY.
export async function recoverSocketAuthentication(sentToken: string | null): Promise<string | null> {
  const current = getAccessToken()
  if (!current) return null // Explicit sign-out must not be undone.
  if (current !== sentToken) return current
  try {
    return await refreshAccessToken()
  } catch {
    return null
  }
}
