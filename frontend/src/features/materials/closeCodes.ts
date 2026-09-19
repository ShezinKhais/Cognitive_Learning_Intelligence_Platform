// What to do when the progress socket closes, by close code. The 4xxx codes
// are the server's, listed in backend/app/api/v1/ws.py.
export type CloseAction = 'sign-in' | 'stop' | 'retry'

export function actionForClose(code: number): CloseAction {
  // 4001: authentication required or failed. The token is no good.
  if (code === 4001) return 'sign-in'
  // 4003: not permitted to join. 4400: malformed event. Sending the same
  // handshake again fails the same way, so retrying only loops forever.
  if (code === 4003 || code === 4400) return 'stop'
  // Everything else, a dropped network, a restart, 1013 "try again later" or
  // the 4408 auth timeout, can succeed on another attempt.
  return 'retry'
}
