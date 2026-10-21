// A showcase of the camera attention signal (gaze-demo.html). It runs the
// same judgement as the classroom (faceFeatures, classifyFace, calibrate from
// signals.ts) but on this page instead of in the worker, so it can draw the
// landmarks the judgement is made from. Nothing is sent or stored. Served by
// `npm run dev` at /eval/gaze-demo.html; not part of the built app.
import '../src/index.css'
import { createRoot } from 'react-dom/client'

import { GazeDemo } from './GazeDemo.tsx'

// Follow the system theme, as the app does outside Teams.
const darkQuery = matchMedia('(prefers-color-scheme: dark)')
const applyTheme = () => document.documentElement.classList.toggle('dark', darkQuery.matches)
applyTheme()
darkQuery.addEventListener('change', applyTheme)

createRoot(document.getElementById('root')!).render(<GazeDemo />)
