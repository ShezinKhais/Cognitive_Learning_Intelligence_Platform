import { useState } from 'react'
import { createRoot } from 'react-dom/client'
import { saveAccessToken, type Question } from '../../src/api'
import WriteQuestionForm from '../../src/features/review/WriteQuestionForm'
import LessonQuestionPlan from '../../src/features/live/LessonQuestionPlan'
import '../../src/index.css'

saveAccessToken('synthetic-test-only')
export function Harness() {
  const [pending, setPending] = useState(false)
  const [saved, setSaved] = useState<Question | null>(null)
  const [checks, setChecks] = useState(0)
  return <main className="mx-auto max-w-3xl p-5">
    <h1 className="mb-4 text-xl font-bold">Lesson preparation</h1>
    {new URLSearchParams(location.search).has('write') ? <>
      <WriteQuestionForm materialId="material-test" onCancel={() => {}} onSaved={setSaved} />
      {saved && <p role="status">Saved question: {saved.prompt}</p>}
    </> : <>
      <LessonQuestionPlan sessionId="lesson-test" onPendingChange={setPending} onSaved={() => setChecks(value => value + 1)} />
      <button disabled={pending} className="mt-4 rounded border p-3">Start test lesson</button>
      <p>Readiness refreshes: {checks}</p>
    </>}
  </main>
}
createRoot(document.getElementById('root')!).render(<Harness />)
