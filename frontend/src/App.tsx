import { Navigate, Route, Routes } from 'react-router'

import StudentHomePage from './pages/StudentHomePage'
import SystemStatusPage from './pages/SystemStatusPage'

export default function App() {
  return (
    <Routes>
      <Route
        path="/"
        element={<Navigate to="/student" replace />}
      />

      <Route
        path="/student"
        element={<StudentHomePage />}
      />

      <Route
        path="/status"
        element={<SystemStatusPage />}
      />

      <Route
        path="*"
        element={<Navigate to="/student" replace />}
      />
    </Routes>
  )
}
