import { clearAccessToken, renewSession } from '../../api'

/** The sign-in page's note when the server could not be told. */
export const SIGN_OUT_INCOMPLETE = 'signout=incomplete'

/**
 * End the sign-in, wait for the server to drop the refresh cookie, then go
 * to the sign-in page. Leaving first could cancel the request and leave the
 * cookie, so the next page load would sign the same person back in. When the
 * server cannot be reached, the sign-in page says so.
 */
export async function signOutToLogin(): Promise<void> {
  const cleared = await clearAccessToken()
  window.location.assign(cleared ? '/login' : `/login?${SIGN_OUT_INCOMPLETE}`)
}

/**
 * A live socket the server refused for its token. The token may have run
 * out while the tab slept, so it is renewed once and the socket reconnects.
 * A server that cannot be reached is tried again later and the user stays
 * signed in, so a dropped connection at that moment does not end a class.
 * Only a refusal from the server sends the user to sign in.
 */
export function renewAfterRefusal({
  stopped,
  reconnect,
  retryLater,
}: {
  stopped: () => boolean
  reconnect: () => void
  retryLater: () => void
}): void {
  void renewSession().then((outcome) => {
    if (stopped()) return
    if (outcome === 'renewed') reconnect()
    else if (outcome === 'unreachable') retryLater()
    else signOutToLogin()
  })
}
