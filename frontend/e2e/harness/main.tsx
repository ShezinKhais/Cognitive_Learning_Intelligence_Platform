import { useState } from 'react'
import { createRoot } from 'react-dom/client'
import { AttentionControls } from '../../src/features/attention/AttentionControls'
import { SocraticChatPanel } from '../../src/features/chat/SocraticChatPanel'
import { useLiveSession as useStudentSession } from '../../src/features/student/useLiveSession'
import { useLiveSession as useLecturerSession } from '../../src/features/live/useLiveSession'
import { useMaterialProgress } from '../../src/features/materials/useMaterialProgress'
import { BreakoutRoomSelection } from '../../src/features/student/BreakoutRoomSelection'
import '../../src/index.css'

export function Harness() {
  const [enabled, setEnabled] = useState(true)
  const [mounted, setMounted] = useState(true)
  const [rejected, setRejected] = useState(0)
  return <main>
    <button onClick={() => setEnabled(!enabled)}>Toggle session connection</button>
    <button onClick={() => setMounted(!mounted)}>Toggle sensor mount</button>
    <button onClick={() => setRejected(rejected + 1)}>Reject consent</button>
    {mounted && <AttentionControls enabled={enabled} consentRejected={rejected} onSignal={value => {
      window.dispatchEvent(new CustomEvent('test-summary', { detail: value }))
      return true
    }} />}
    <SocraticChatPanel sessionId="phase8" />
  </main>
}
function StudentSocket() {
  const { state, selectRoom } = useStudentSession('refresh-session', 'active')
  return <main>Student socket: {state.connection}
    <BreakoutRoomSelection key={state.connection} onSelect={selectRoom} serverError={state.error}
      enabled={state.connection === 'connected' && state.sessionStatus === 'active' && !state.paused} />
  </main>
}
function LecturerSocket() {
  const { connectionStatus } = useLecturerSession('refresh-session')
  return <main>Lecturer socket: {connectionStatus}</main>
}
function ProgressSocket() {
  const status = useMaterialProgress(() => {})
  return <main>Progress socket: {status}</main>
}
const socket = new URLSearchParams(window.location.search).get('socket')
createRoot(document.getElementById('root')!).render(
  socket === 'student' ? <StudentSocket /> :
  socket === 'lecturer' ? <LecturerSocket /> :
  socket === 'progress' ? <ProgressSocket /> : <Harness />,
)
