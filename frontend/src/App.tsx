import {
  Navigate,
  Route,
  Routes,
} from 'react-router'

import { StudentAppProvider } from './features/student/StudentAppContext'
import AccessDeniedPage from './pages/AccessDeniedPage'
import LoginPage from './pages/LoginPage'
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
