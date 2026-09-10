import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Route, Routes } from 'react-router'
import './index.css'
import App from './App.tsx'
import AccessDeniedPage from './pages/AccessDeniedPage.tsx'
import AdminConsole from './pages/AdminConsole.tsx'
import ConsentPage from './pages/ConsentPage.tsx'
import LoginPage from './pages/LoginPage.tsx'
import ProtectedAdminRoute from './pages/ProtectedAdminRoute.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<App />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/consent" element={<ConsentPage />} />
        <Route path="/access-denied" element={<AccessDeniedPage />} />
        <Route element={<ProtectedAdminRoute />}>
          <Route path="/admin" element={<AdminConsole />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </StrictMode>,
)
