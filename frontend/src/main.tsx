import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router'

import App from './App.tsx'
import './index.css'
import { TeamsProvider } from './teams/TeamsProvider.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <TeamsProvider>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </TeamsProvider>
  </StrictMode>,
)
