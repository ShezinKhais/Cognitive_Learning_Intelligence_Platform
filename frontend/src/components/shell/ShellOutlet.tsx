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
  const { pathname } = useLocation()
  return (
    <AppShell user={user}>
      {/* A page fetched for the first time loads inside the shell, so the
          navigation stays put rather than the screen going blank. */}
      {/* Keyed by page, so leaving a page that failed clears the error. */}
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
    </AppShell>
  )
}
