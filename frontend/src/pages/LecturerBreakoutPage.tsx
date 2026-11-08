import { useCallback, useEffect, useId, useMemo, useState } from 'react'
import { Link } from 'react-router'
import { Shuffle, Undo2, Users } from 'lucide-react'

import { ApiError } from '../api'
import { buttonStyles } from '../components/ui/button'
import { EmptyState, MetaLine, PageBody, PageHeader, Panel, SkeletonRows, Tag } from '../components/ui/primitives'
import { ProblemState } from '../components/ui/ProblemState'
import { problemArt, problemOf, type Problem } from '../components/ui/problem'
import { useToast } from '../components/ui/toast'
import { planBody, roomLabels, splitEvenly, type Draft } from '../features/rooms/roomPlan'
import { closeRooms, getRoomPlan, sendRoomPlan, type RoomMember, type RoomPlan } from '../features/rooms/roomsApi'
import { listSessions, type SessionSummary } from '../features/sessions/sessionsApi'

const FIELD = 'rounded-md border border-input bg-background px-3 py-2 text-sm'

/** Split a running class into breakout rooms. Teams has no way for an app to
 * make rooms, so each student's panel says which room to join, and the
 * lecturer opens rooms with the same names in Teams. */
export default function LecturerBreakoutPage() {
  const [running, setRunning] = useState<SessionSummary[] | null>(null)
  const [chosen, setChosen] = useState<string | null>(null)
  const [error, setError] = useState<Problem | null>(null)
  const pickerId = useId()

  const load = useCallback(() => {
    setError(null)
    listSessions().then(
      (page) => {
        const active = page.items.filter((session) => session.status === 'active')
        setRunning(active)
        setChosen((current) => (current && active.some((s) => s.id === current) ? current : (active[0]?.id ?? null)))
      },
      (caught: unknown) => setError(problemOf(caught, 'Check your connection and try again.')),
    )
  }, [])
  useEffect(load, [load])

  return (
    <>
      <PageHeader
        title="Breakout rooms"
        description="Split a running class into rooms. Each student's C.L.I.P panel says which room to join, and your live page shows which rooms have gone quiet."
        actions={
          running && running.length > 1 ? (
            <div>
              <label htmlFor={pickerId} className="sr-only">
                Class
              </label>
              <select id={pickerId} value={chosen ?? ''} onChange={(e) => setChosen(e.target.value)} className={FIELD}>
                {running.map((session) => (
                  <option key={session.id} value={session.id}>
                    {session.course_code}: {session.title}
                  </option>
                ))}
              </select>
            </div>
          ) : undefined
        }
      />
      <PageBody>
        {error ? (
          <ProblemState art={problemArt(error.cause)} title="Your classes could not be loaded" retry={load}>
            {error.message}
          </ProblemState>
        ) : !running ? (
          <SkeletonRows label="Loading your classes" rows={2} />
        ) : !chosen ? (
          <EmptyState art="lecture" title="No class is running">
            Start a class, then split it into rooms here.{' '}
            <Link to="/lecturer/sessions" className="font-semibold underline">
              Go to your sessions
            </Link>
          </EmptyState>
        ) : (
          <Planner key={chosen} session={running.find((s) => s.id === chosen)!} />
        )}
      </PageBody>
    </>
  )
}

function draftOf(plan: RoomPlan): Draft {
  const draft: Draft = {}
  for (const room of plan.rooms) for (const student of room.students) draft[student.user_id] = room.label
  for (const student of plan.unassigned) draft[student.user_id] = null
  return draft
}

function Planner({ session }: { session: SessionSummary }) {
  const notify = useToast()
  const [plan, setPlan] = useState<RoomPlan | null>(null)
  const [draft, setDraft] = useState<Draft>({})
  const [count, setCount] = useState(2)
  const [onlyConnected, setOnlyConnected] = useState(true)
  const [busy, setBusy] = useState<'send' | 'close' | null>(null)
  const [error, setError] = useState<Problem | null>(null)
  const countId = useId()
  const connectedId = useId()

  const load = useCallback(() => {
    setError(null)
    getRoomPlan(session.id).then(
      (found) => {
        setPlan(found)
        setDraft(draftOf(found))
        if (found.rooms.length > 0) setCount(found.rooms.length)
      },
      (caught: unknown) => setError(problemOf(caught, 'Check your connection and try again.')),
    )
  }, [session.id])
  useEffect(load, [load])

  const students = useMemo<RoomMember[]>(
    () =>
      plan
        ? [...plan.rooms.flatMap((room) => room.students), ...plan.unassigned].sort((a, b) => a.name.localeCompare(b.name))
        : [],
    [plan],
  )
  const labels = useMemo(() => {
    const used = Object.values(draft).filter((label): label is string => Boolean(label))
    return [...new Set([...roomLabels(count), ...used])].sort((a, b) => a.localeCompare(b, undefined, { numeric: true }))
  }, [count, draft])
  const placed = Object.values(draft).filter(Boolean).length
  const sent = plan ? plan.rooms.length > 0 : false

  function split() {
    const pool = students.filter((student) => !onlyConnected || student.connected).map((student) => student.user_id)
    const dealt = splitEvenly(pool, count)
    setDraft(Object.fromEntries(students.map((student) => [student.user_id, dealt[student.user_id] ?? null])))
  }

  function act(kind: 'send' | 'close') {
    setBusy(kind)
    const request = kind === 'send' ? sendRoomPlan(session.id, planBody(draft)) : closeRooms(session.id)
    request.then(
      (next) => {
        setBusy(null)
        setPlan(next)
        setDraft(draftOf(next))
        notify(kind === 'send' ? 'Rooms sent to students' : 'Everyone has been told to come back')
      },
      (caught: unknown) => {
        setBusy(null)
        notify(caught instanceof ApiError ? caught.message : 'That could not be done. Try again.', { tone: 'problem' })
      },
    )
  }

  if (error) {
    return (
      <ProblemState art={problemArt(error.cause)} title="The rooms could not be loaded" retry={load}>
        {error.message}
      </ProblemState>
    )
  }
  if (!plan) return <SkeletonRows label="Loading the rooms" rows={2} />

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_22rem]">
      <Panel
        title={`${session.course_code}: ${session.title}`}
        description={`${students.length} students on the course, ${students.filter((s) => s.connected).length} with the class open.`}
        actions={sent ? <Tag tone="live">Rooms open</Tag> : undefined}
      >
        {students.length === 0 ? (
          <p className="text-sm text-muted-foreground">Nobody is enrolled on this course yet.</p>
        ) : (
          <>
            <div className="flex flex-wrap items-end gap-3">
              <div>
                <label htmlFor={countId} className="text-sm font-semibold">
                  Rooms
                </label>
                <input
                  id={countId}
                  type="number"
                  min={1}
                  max={50}
                  value={count}
                  onChange={(e) => setCount(Math.min(50, Math.max(1, Number(e.target.value) || 1)))}
                  className={`${FIELD} mt-1 block w-24`}
                />
              </div>
              <label htmlFor={connectedId} className="flex items-center gap-2 pb-2 text-sm">
                <input
                  id={connectedId}
                  type="checkbox"
                  checked={onlyConnected}
                  onChange={(e) => setOnlyConnected(e.target.checked)}
                />
                Only students with the class open
              </label>
              <button type="button" className={buttonStyles({ intent: 'secondary' })} onClick={split}>
                <Shuffle size={16} aria-hidden />
                Split evenly
              </button>
            </div>

            <ul className="mt-4 divide-y divide-border">
              {students.map((student) => (
                <li key={student.user_id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                  <div className="min-w-0">
                    <p className="font-semibold">{student.name}</p>
                    <MetaLine items={[student.connected ? 'Class open' : 'Not connected']} />
                  </div>
                  <select
                    aria-label={`Room for ${student.name}`}
                    value={draft[student.user_id] ?? ''}
                    onChange={(e) => setDraft({ ...draft, [student.user_id]: e.target.value || null })}
                    className={FIELD}
                  >
                    <option value="">No room</option>
                    {labels.map((label) => (
                      <option key={label} value={label}>
                        {label}
                      </option>
                    ))}
                  </select>
                </li>
              ))}
            </ul>

            <div className="mt-4 flex flex-wrap gap-2">
              <button
                type="button"
                className={buttonStyles()}
                disabled={busy !== null || placed === 0}
                onClick={() => act('send')}
              >
                <Users size={16} aria-hidden />
                {busy === 'send' ? 'Sending…' : sent ? 'Send the changes' : 'Send rooms to students'}
              </button>
              {sent && (
                <button
                  type="button"
                  className={buttonStyles({ intent: 'secondary' })}
                  disabled={busy !== null}
                  onClick={() => act('close')}
                >
                  <Undo2 size={16} aria-hidden />
                  {busy === 'close' ? 'Bringing back…' : 'Bring everyone back'}
                </button>
              )}
              <Link to={`/lecturer/sessions/${session.id}/live`} className={buttonStyles({ intent: 'quiet' })}>
                Watch the rooms live
              </Link>
            </div>
          </>
        )}
      </Panel>

      <Panel title="In Teams" description="C.L.I.P cannot create Teams rooms, so match them by hand.">
        <ol className="list-decimal space-y-2 pl-5 text-sm">
          <li>Send the rooms here first. Each student's panel then shows their room.</li>
          <li>
            In the meeting, open <strong>Breakout rooms</strong> and create {plan.rooms.length || count} rooms. Name them{' '}
            {(plan.rooms.length ? plan.rooms.map((room) => room.label) : roomLabels(count)).slice(0, 3).join(', ')}
            {(plan.rooms.length || count) > 3 ? ' and so on' : ''}.
          </li>
          <li>Assign the same people, or let students choose their room, then open the rooms.</li>
          <li>When time is up, close the rooms in Teams and select Bring everyone back here.</li>
        </ol>
        <p className="mt-3 text-xs text-muted-foreground">
          Room activity comes from when students speak and answer, never what they say.
        </p>
      </Panel>
    </div>
  )
}
