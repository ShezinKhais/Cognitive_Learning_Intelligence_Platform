import {
  Navigate,
  Route,
  Routes,
} from 'react-router'

import { StudentAppProvider } from './features/student/StudentAppContext'
import AccessDeniedPage from './pages/AccessDeniedPage'
import AdminConsole from './pages/AdminConsole'
import ConsentPage from './pages/ConsentPage'
import LoginPage from './pages/LoginPage'
import ProtectedAdminRoute from './pages/ProtectedAdminRoute'
import ProtectedStudentPage from './pages/ProtectedStudentPage'
import SystemStatusPage from './pages/SystemStatusPage'

export default function App() {
  return (
    <Routes>
      <Route
        path="/"
        element={
          <Navigate
            to="/student"
            replace
          />
        }
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

      {/* The guard is a layout route, so the role check runs before
          AdminConsole mounts and no admin-only markup renders for a
          student who types the URL. */}
      <Route element={<ProtectedAdminRoute />}>
        <Route
          path="/admin"
          element={<AdminConsole />}
        />
      </Route>

      <Route
        path="/status"
        element={<SystemStatusPage />}
      />

      <Route
        path="*"
        element={
          <Navigate
            to="/student"
            replace
          />
        }
      />
    </Routes>
  )
}
