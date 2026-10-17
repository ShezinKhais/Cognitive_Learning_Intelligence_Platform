import { lazy, Suspense } from 'react'
import {
  Navigate,
  Outlet,
  Route,
  Routes,
} from 'react-router'

import { defaultPathForRole } from './authRouting'
import PageLoader from './components/brand/PageLoader'
import PageErrorBoundary from './components/PageErrorBoundary'
import RoleGate from './components/RoleGate'
import ShellOutlet from './components/shell/ShellOutlet'
import StaffTeamsBoundary from './components/StaffTeamsBoundary'
import { StudentAppProvider } from './features/student/StudentAppContext'
import LoginPage from './pages/LoginPage'
import { PLANNED } from './pages/plannedFeatures'
import ProtectedStudentPage from './pages/ProtectedStudentPage'

// Each page is its own chunk, fetched the first time someone opens it, so a
// student signing in does not download the administrator console, the
// lecturer's live view and the charts. Sign-in, the guards and the shell stay
// in the first download: every visit needs them.
const AccessDeniedPage = lazy(() => import('./pages/AccessDeniedPage'))
const AdminConsole = lazy(() => import('./pages/AdminConsole'))
const AdminStatusPage = lazy(() => import('./pages/AdminStatusPage'))
const ConsentPage = lazy(() => import('./pages/ConsentPage'))
const LecturerLiveSessionPage = lazy(() => import('./pages/LecturerLiveSessionPage'))
const LecturerMaterialsPage = lazy(() => import('./pages/LecturerMaterialsPage'))
const LecturerSessionsPage = lazy(() => import('./pages/LecturerSessionsPage'))
const PlannedFeaturePage = lazy(() => import('./pages/PlannedFeaturePage'))
const QuestionReview = lazy(() => import('./pages/QuestionReview'))
const SessionReportPage = lazy(() => import('./pages/SessionReportPage'))
const StudentHomePage = lazy(() => import('./pages/StudentHomePage'))
const StudentLiveSessionPage = lazy(() => import('./pages/StudentLiveSessionPage'))
const StudentSummaryPage = lazy(() => import('./pages/StudentSummaryPage'))
const SystemStatusPage = lazy(() => import('./pages/SystemStatusPage'))
const TeamsConfigPage = lazy(() => import('./pages/TeamsConfigPage'))
const TeamsLecturerMeetingPage = lazy(() => import('./pages/TeamsLecturerMeetingPage'))
const TeamsMeetingEntryPage = lazy(() => import('./pages/TeamsMeetingEntryPage'))
const TeamsMeetingPage = lazy(() => import('./pages/TeamsMeetingPage'))

// Sends whoever arrives at the root, or at a page that does not exist, to
// their own home. Always sending them to /student told every lecturer and
// administrator "Student access required".
const home = (
  <RoleGate allow={['student', 'lecturer', 'admin']}>
    {(user) => <Navigate to={defaultPathForRole(user.role)} replace />}
  </RoleGate>
)

export default function App() {
  return (
    // Pages inside the shell wait inside it (ShellOutlet); this covers the
    // ones that stand alone.
    <PageErrorBoundary fullScreen>
      <Suspense fallback={<PageLoader label="Opening the page" />}>
        <Routes>
          <Route
            path="/"
            element={home}
          />

          <Route
            path="/login"
            element={<LoginPage />}
          />

          <Route
            path="/consent"
            element={<ConsentPage />}
          />

          <Route
            path="/access-denied"
            element={<AccessDeniedPage />}
          />

          {/* Teams loads this before a user enters the authenticated experience.
              The meeting organizer may be a lecturer, so configuration must not
              be protected by the student-only role guard. */}
          <Route
            path="/config"
            element={<TeamsConfigPage />}
          />

          <Route
            path="/student"
            element={
              <StudentAppProvider>
                <ProtectedStudentPage withShell />
              </StudentAppProvider>
            }
          >
            <Route
              index
              element={<StudentHomePage />}
            />
            <Route
              path="session/:sessionId"
              element={<StudentLiveSessionPage />}
            />
            <Route
              path="session/:sessionId/summary"
              element={<StudentSummaryPage />}
            />
            <Route
              path="progress"
              element={<PlannedFeaturePage feature={PLANNED.progress} />}
            />
            <Route
              path="consideration"
              element={<PlannedFeaturePage feature={PLANNED.consideration} />}
            />
          </Route>

          {/* Shared Teams meeting entry point. RoleGate first verifies the
              authoritative C.L.I.P user. Students continue into the existing
              student Teams experience, while lecturer/admin users are redirected
              by TeamsMeetingEntryPage to the protected lecturer Teams surface. */}
          <Route
            path="/teams"
            element={<TeamsMeetingEntryPage />}
          >
            <Route
              path="meeting"
              element={
                <StudentAppProvider>
                  <ProtectedStudentPage />
                </StudentAppProvider>
              }
            >
              <Route
                index
                element={<TeamsMeetingPage />}
              />
            </Route>
          </Route>

          {/* The guard is a layout route, so the role check runs before
              AdminConsole mounts and no admin-only markup renders for a
              student who types the URL. */}
          <Route
            element={
              <RoleGate allow={['admin']}>
                {(user) => <Outlet context={user} />}
              </RoleGate>
            }
          >
            <Route element={<ShellOutlet />}>
              <Route
                path="/admin"
                element={<AdminConsole />}
              />
              <Route
                path="/admin/status"
                element={<AdminStatusPage />}
              />
              <Route
                path="/admin/governance"
                element={<PlannedFeaturePage feature={PLANNED.governance} />}
              />
            </Route>
          </Route>

          {/* Lecturers, and admins who can review on any lecturer's behalf per
              the backend's ownership check, reach the materials workspace and the
              review screen; students never see either mount.

              RoleGate remains authoritative for authentication, role and consent.
              StaffTeamsBoundary receives that verified C.L.I.P identity but Teams
              context must never be allowed to grant staff access. */}
          <Route
            element={
              <RoleGate allow={['lecturer', 'admin']}>
                {(user) => (
                  <StaffTeamsBoundary user={user}>
                    <Outlet context={user} />
                  </StaffTeamsBoundary>
                )}
              </RoleGate>
            }
          >
            {/* The meeting side panel is too narrow for the shell. */}
            <Route
              path="/lecturer/teams/meeting"
              element={<TeamsLecturerMeetingPage />}
            />

            <Route element={<ShellOutlet />}>
              <Route
                path="/lecturer"
                element={
                  <Navigate
                    to="/lecturer/sessions"
                    replace
                  />
                }
              />

              <Route
                path="/lecturer/materials"
                element={<LecturerMaterialsPage />}
              />

              <Route
                path="/lecturer/sessions"
                element={<LecturerSessionsPage />}
              />

              <Route
                path="/lecturer/sessions/:sessionId/live"
                element={<LecturerLiveSessionPage />}
              />

              <Route
                path="/lecturer/sessions/:sessionId/report"
                element={<SessionReportPage />}
              />

              <Route
                path="/lecturer/groups"
                element={<PlannedFeaturePage feature={PLANNED.groups} />}
              />

              <Route
                path="/lecturer/engagement"
                element={<PlannedFeaturePage feature={PLANNED.engagement} />}
              />

              <Route
                path="/materials/:materialId/review"
                element={<QuestionReview />}
              />
            </Route>
          </Route>

          <Route
            path="/status"
            element={<SystemStatusPage />}
          />

          <Route
            path="*"
            element={home}
          />
        </Routes>
      </Suspense>
    </PageErrorBoundary>
  )
}