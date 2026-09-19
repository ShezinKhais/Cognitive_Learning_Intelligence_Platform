import {
  Navigate,
  Outlet,
  Route,
  Routes,
} from 'react-router'

import { defaultPathForRole } from './authRouting'
import RoleGate from './components/RoleGate'
import { StudentAppProvider } from './features/student/StudentAppContext'
import AccessDeniedPage from './pages/AccessDeniedPage'
import AdminConsole from './pages/AdminConsole'
import ConsentPage from './pages/ConsentPage'
import LecturerLiveSessionPage from './pages/LecturerLiveSessionPage'
import LecturerMaterialsPage from './pages/LecturerMaterialsPage'
import LoginPage from './pages/LoginPage'
import ProtectedStudentPage from './pages/ProtectedStudentPage'
import QuestionReview from './pages/QuestionReview'
import SystemStatusPage from './pages/SystemStatusPage'

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
        path="/student"
        element={
          <StudentAppProvider>
            <ProtectedStudentPage />
          </StudentAppProvider>
        }
      />

      <Route element={<RoleGate allow={['admin']}>{() => <Outlet />}</RoleGate>}>
        <Route
          path="/admin"
          element={<AdminConsole />}
        />
      </Route>

      <Route element={<RoleGate allow={['lecturer', 'admin']}>{() => <Outlet />}</RoleGate>}>
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
          path="/lecturer/sessions/:sessionId/live"
          element={<LecturerLiveSessionPage />}
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