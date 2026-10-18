import { Suspense } from 'react'
import { Outlet, useLocation, useOutletContext } from 'react-router'

import type { CurrentUser } from '../../api'
import PageErrorBoundary from '../PageErrorBoundary'
import { PageBody, SkeletonRows } from '../ui/primitives'
import AppShell from './AppShell'

/** A layout route that frames its child pages in the shell, for the user a
 * guard above it verified and passed down as outlet context. */
export default function ShellOutlet() {
  const user = useOutletContext<CurrentUser>()
  return (
    <AppShell user={user}>
      <PageOutlet />
    </AppShell>
  )
}

/** The child page, inside the boundary and loading frame every shell page has. */
export function PageOutlet() {
  const { pathname } = useLocation()
  return (
    // A page fetched for the first time loads inside the shell, so the
    // navigation stays put rather than the screen going blank. Keyed by page,
    // so leaving a page that failed clears the error.
    <PageErrorBoundary key={pathname}>
      <Suspense
        fallback={
          <PageBody>
            <SkeletonRows label="Opening the page" />
          </PageBody>
        }
      >
        <Outlet />
      </Suspense>
    </PageErrorBoundary>
  )
}
