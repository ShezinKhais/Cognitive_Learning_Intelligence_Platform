import { clearAccessToken, renewSession } from '../../api'

/** End the sign-in and go to the sign-in page. */
export function signOutToLogin(): void {
  clearAccessToken()
  window.location.assign('/login')
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
