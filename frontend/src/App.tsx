import {
  Navigate,
  Outlet,
  Route,
  Routes,
} from 'react-router'

import { defaultPathForRole } from './authRouting'
import RoleGate from './components/RoleGate'
import StaffTeamsBoundary from './components/StaffTeamsBoundary'
import { StudentAppProvider } from './features/student/StudentAppContext'
import AccessDeniedPage from './pages/AccessDeniedPage'
import AdminConsole from './pages/AdminConsole'
import AdminGovernancePage from './pages/AdminGovernancePage'
import ConsentPage from './pages/ConsentPage'
import LecturerLiveSessionPage from './pages/LecturerLiveSessionPage'
import LecturerMaterialsPage from './pages/LecturerMaterialsPage'
import LecturerSessionReportPage from './pages/LecturerSessionReportPage'
import LecturerSessionsPage from './pages/LecturerSessionsPage'
import LoginPage from './pages/LoginPage'
import ProtectedStudentPage from './pages/ProtectedStudentPage'
import QuestionReview from './pages/QuestionReview'
import StudentHomePage from './pages/StudentHomePage'
import StudentLiveSessionPage from './pages/StudentLiveSessionPage'
import SystemStatusPage from './pages/SystemStatusPage'
import TeamsConfigPage from './pages/TeamsConfigPage'
import TeamsLecturerMeetingPage from './pages/TeamsLecturerMeetingPage'
import TeamsMeetingEntryPage from './pages/TeamsMeetingEntryPage'
import TeamsMeetingPage from './pages/TeamsMeetingPage'

const home = (
  <RoleGate allow={['student', 'lecturer', 'admin']}>
    {(user) => <Navigate to={defaultPathForRole(user.role)} replace />}
  </RoleGate>
)

export default function App() {
  return (
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

      <Route
        path="/config"
        element={<TeamsConfigPage />}
      />

      <Route
        path="/student"
        element={
          <StudentAppProvider>
            <ProtectedStudentPage />
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
      </Route>

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

      <Route
        element={
          <RoleGate allow={['admin']}>
            {() => <Outlet />}
          </RoleGate>
        }
      >
        <Route
          path="/admin"
          element={<AdminConsole />}
        />

        <Route
          path="/admin/governance"
          element={<AdminGovernancePage />}
        />
      </Route>

      <Route
        element={
          <RoleGate allow={['lecturer', 'admin']}>
            {(user) => (
              <StaffTeamsBoundary user={user}>
                <Outlet />
              </StaffTeamsBoundary>
            )}
          </RoleGate>
        }
      >
        <Route
          path="/lecturer"
          element={
            <Navigate
              to="/lecturer/materials"
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
          element={<LecturerSessionReportPage />}
        />

        <Route
          path="/lecturer/teams/meeting"
          element={<TeamsLecturerMeetingPage />}
        />

        <Route
          path="/materials/:materialId/review"
          element={<QuestionReview />}
        />
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
  )
}