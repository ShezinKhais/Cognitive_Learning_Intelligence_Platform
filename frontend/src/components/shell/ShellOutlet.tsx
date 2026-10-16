import { Outlet, useOutletContext } from 'react-router'

import type { CurrentUser } from '../../api'
import AppShell from './AppShell'

/** A layout route that frames its child pages in the shell, for the user a
 * guard above it verified and passed down as outlet context. */
export default function ShellOutlet() {
  const user = useOutletContext<CurrentUser>()
  return (
    <AppShell user={user}>
      <Outlet />
    </AppShell>
  )
}
