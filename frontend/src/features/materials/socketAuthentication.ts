import { getAccessToken, refreshAccessToken } from '../../api'

// A socket may outlive its credential, or race an HTTP refresh. Reuse a
// newer credential before requesting a refresh. The hook bounds this to one
// recovery attempt until the server accepts the handshake with READY.
export async function recoverSocketAuthentication(
  sentToken: string | null,
): Promise<'renewed' | 'refused' | 'unreachable'> {
  const current = getAccessToken()
  if (!current) return 'refused' // Explicit sign-out must not be undone.
  if (current !== sentToken) return 'renewed'
  try {
    if (await refreshAccessToken()) return 'renewed'
  } catch {
    // An interrupted/malformed response is not proof of rejected credentials.
  }
  // Current main's refresh clears the token only on a definitive 401;
  // network/5xx failures keep it. #164 exposes these outcomes as renewSession;
  // keep its implementation when that cookie-auth rework is integrated.
  return getAccessToken() ? 'unreachable' : 'refused'
}
