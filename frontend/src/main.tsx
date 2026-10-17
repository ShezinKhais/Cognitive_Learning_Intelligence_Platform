import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router'
import { MotionConfig } from 'motion/react'

import App from './App.tsx'
import '@fontsource-variable/atkinson-hyperlegible-next'
import './index.css'
import { TeamsProvider } from './teams'
import { followStoredTheme } from './components/shell/theme'
import { ToastProvider } from './components/ui/toast'

// Paint the saved theme before the first frame; Teams replaces it in a meeting.
followStoredTheme()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <TeamsProvider>
      {/* "user": travel and scale are dropped when the device asks for reduced
          motion; fades and colour changes still run. */}
      <MotionConfig reducedMotion="user">
        <ToastProvider>
          <BrowserRouter>
            <App />
          </BrowserRouter>
        </ToastProvider>
      </MotionConfig>
    </TeamsProvider>
  </StrictMode>,
)
