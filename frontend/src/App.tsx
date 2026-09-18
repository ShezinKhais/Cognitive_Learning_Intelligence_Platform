import {
  Navigate,
  Route,
  Routes,
} from 'react-router'

import { StudentAppProvider } from './features/student/StudentAppContext'
import AccessDeniedPage from './pages/AccessDeniedPage'
import AdminConsole from './pages/AdminConsole'
import ConsentPage from './pages/ConsentPage'
import LecturerMaterialsPage from './pages/LecturerMaterialsPage'
import LoginPage from './pages/LoginPage'
import ProtectedAdminRoute from './pages/ProtectedAdminRoute'
import ProtectedLecturerRoute from './pages/ProtectedLecturerRoute'
import ProtectedStudentPage from './pages/ProtectedStudentPage'
import QuestionReview from './pages/QuestionReview'
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

      {/* Lecturers, and admins who can review on any lecturer's behalf per
          the backend's ownership check, reach the materials workspace and the
          review screen; students never see either mount. */}
      <Route element={<ProtectedLecturerRoute />}>
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
