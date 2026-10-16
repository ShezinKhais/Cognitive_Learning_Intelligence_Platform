import { useState } from 'react'
import { createRoot } from 'react-dom/client'
import { AttentionControls } from '../../src/features/attention/AttentionControls'
import { SocraticChatPanel } from '../../src/features/chat/SocraticChatPanel'
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
createRoot(document.getElementById('root')!).render(<Harness />)
