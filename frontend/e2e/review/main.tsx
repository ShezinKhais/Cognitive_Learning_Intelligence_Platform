import { createRoot } from 'react-dom/client'
import { MemoryRouter, Route, Routes } from 'react-router'
import StudentReviewPage from '../../src/pages/StudentReviewPage'
import { saveAccessToken } from '../../src/api'
import '../../src/index.css'

// Synthetic identity only; this entry is excluded from production builds.
saveAccessToken('test-only')
createRoot(document.getElementById('root')!).render(
  <MemoryRouter initialEntries={['/student/reviews/review-session']}>
    <Routes><Route path="/student/reviews/:sessionId" element={<StudentReviewPage />} /></Routes>
  </MemoryRouter>,
)
