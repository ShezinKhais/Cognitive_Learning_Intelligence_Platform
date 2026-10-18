import { LogOut } from 'lucide-react'

import { signOutToLogin } from '../features/realtime/tokenRefusal'

/**
 * Ends the session on this device and returns to the sign-in page, once the
 * server has dropped the refresh cookie.
 *
 * A full page load rather than a router navigation, so nothing the signed-out
 * user loaded (their sessions, an open progress socket) survives into the
 * next sign-in.
 */
export default function SignOutButton() {
  return (
    <button
      type="button"
      onClick={() => void signOutToLogin()}
      className="inline-flex shrink-0 items-center gap-2 rounded-lg border border-border bg-card px-3 py-2 text-sm font-medium hover:bg-muted"
    >
      <LogOut aria-hidden="true" size={16} />
      Sign out
    </button>
  )
}
