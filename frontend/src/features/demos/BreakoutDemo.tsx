import { useEffect, useMemo, useState } from 'react'
import { AnimatePresence, LayoutGroup, motion } from 'motion/react'
import { Minus, Plus, Shuffle, Undo2 } from 'lucide-react'

import { buttonStyles } from '../../components/ui/button'
import { Tag, type Tone } from '../../components/ui/primitives'
import { ACTIVITY_LABEL, describeSilence, type RoomActivity } from '../live/rooms'
import DemoFrame from './DemoFrame'
import { formGroups, SAMPLE_STUDENTS, seeded } from './sampleData'

// The demo runs ten times faster than a class, so a room goes quiet in
// seconds rather than minutes.
const TICK_MS = 1000
const SECONDS_PER_TICK = 10
const QUIET_AFTER = 30
const NEEDS_YOU_AFTER = 90

interface Room {
  label: string
  members: string[]
  silence: number
  speaking: number
  answers: number
}

function activity(room: Room): RoomActivity {
  if (room.speaking > 0) return 'active'
  if (room.silence >= NEEDS_YOU_AFTER) return 'needs_attention'
  if (room.silence >= QUIET_AFTER) return 'quiet'
  return 'active'
}

const ORDER: Record<RoomActivity, number> = { needs_attention: 0, quiet: 1, unknown: 2, active: 3 }
const TONE: Record<RoomActivity, Tone> = { active: 'good', quiet: 'mixed', needs_attention: 'poor', unknown: 'neutral' }

export default function BreakoutDemo() {
  const [size, setSize] = useState(4)
  const [seed, setSeed] = useState(1)
  const [running, setRunning] = useState(false)
  const groups = useMemo(() => formGroups(SAMPLE_STUDENTS, size, seed), [size, seed])
  const [rooms, setRooms] = useState<Room[]>([])

  useEffect(() => {
    if (!running) return
    const random = seeded(seed * 97)
    const timer = window.setInterval(() => {
      setRooms((current) =>
        current.map((room, index) => {
          // Some rooms talk more than others; the last one is the quiet one.
          const chatty = index === current.length - 1 ? 0.12 : 0.55
          const speaking = random() < chatty ? 1 + Math.floor(random() * 2) : 0
          return {
            ...room,
            speaking,
            silence: speaking ? 0 : room.silence + SECONDS_PER_TICK,
            answers: room.answers + (random() < 0.15 ? 1 : 0),
          }
        }),
      )
    }, TICK_MS)
    return () => window.clearInterval(timer)
  }, [running, seed])

  function start() {
    setRooms(groups.map((members, index) => ({ label: `Room ${index + 1}`, members, silence: 0, speaking: 0, answers: 0 })))
    setRunning(true)
  }

  function nudge(label: string) {
    setRooms((current) => current.map((room) => (room.label === label ? { ...room, silence: 0, speaking: 1 } : room)))
  }

  const needYou = rooms.filter((room) => activity(room) === 'needs_attention').length

  return (
    <DemoFrame note="Runs ten times faster than a real class. Nothing is saved.">
      {!running ? (
        <>
          <div className="flex flex-wrap items-center gap-4">
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold">Group size</span>
              <div className="flex items-center rounded-md border border-input">
                <button type="button" className="p-2 hover:bg-muted disabled:opacity-40" onClick={() => setSize((n) => n - 1)} disabled={size <= 2} aria-label="Smaller groups">
                  <Minus size={16} aria-hidden />
                </button>
                <span className="w-8 text-center font-bold" aria-live="polite">{size}</span>
                <button type="button" className="p-2 hover:bg-muted disabled:opacity-40" onClick={() => setSize((n) => n + 1)} disabled={size >= 6} aria-label="Bigger groups">
                  <Plus size={16} aria-hidden />
                </button>
              </div>
            </div>
            <button type="button" className={buttonStyles({ intent: 'secondary' })} onClick={() => setSeed((n) => n + 1)}>
              <Shuffle size={16} aria-hidden />
              Shuffle
            </button>
            <button type="button" className={buttonStyles()} onClick={start}>
              Start breakout with {groups.length} rooms
            </button>
          </div>
          <LayoutGroup>
            <ul className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {groups.map((members, index) => (
                <motion.li layout key={`room-${index}`} className="rounded-md border border-border px-4 py-3">
                  <p className="font-bold">Room {index + 1}</p>
                  <ul className="mt-2 flex flex-wrap gap-1.5">
                    {members.map((name) => (
                      <motion.li
                        layout
                        layoutId={name}
                        key={name}
                        transition={{ type: 'spring', stiffness: 500, damping: 40 }}
                        className="rounded bg-muted px-2 py-0.5 text-sm"
                      >
                        {name}
                      </motion.li>
                    ))}
                  </ul>
                </motion.li>
              ))}
            </ul>
          </LayoutGroup>
        </>
      ) : (
        <>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p aria-live="polite">
              {needYou > 0 ? (
                <strong className="text-critical">
                  {needYou} {needYou === 1 ? 'room has' : 'rooms have'} been quiet for a while
                </strong>
              ) : (
                <span className="text-muted-foreground">Every room is talking or was a moment ago.</span>
              )}
            </p>
            <button type="button" className={buttonStyles({ intent: 'secondary' })} onClick={() => setRunning(false)}>
              <Undo2 size={16} aria-hidden />
              Bring everyone back
            </button>
          </div>
          <ul className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <AnimatePresence initial={false}>
              {[...rooms]
                // Rooms that need you first; within a state, a room keeps its place.
                .sort((a, b) => ORDER[activity(a)] - ORDER[activity(b)] || a.label.localeCompare(b.label, undefined, { numeric: true }))
                .map((room) => {
                  const state = activity(room)
                  return (
                    <motion.li
                      layout
                      key={room.label}
                      transition={{ type: 'spring', stiffness: 400, damping: 36 }}
                      className={`rounded-md border px-4 py-3 transition-colors ${state === 'needs_attention' ? 'border-critical/40 bg-critical/5' : 'border-border'}`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-bold">{room.label}</span>
                        <Tag tone={TONE[state]}>{ACTIVITY_LABEL[state]}</Tag>
                      </div>
                      <p className="mt-1 text-sm text-muted-foreground">
                        {room.members.length} students,{' '}
                        {room.speaking > 0 ? `${room.speaking} speaking` : describeSilence(room.silence).toLowerCase()}
                        {room.answers > 0 && `, ${room.answers} ${room.answers === 1 ? 'answer' : 'answers'}`}
                      </p>
                      {state !== 'active' && (
                        <button type="button" className="mt-2 text-sm font-semibold text-primary link-sweep" onClick={() => nudge(room.label)}>
                          Drop in on {room.label}
                        </button>
                      )}
                    </motion.li>
                  )
                })}
            </AnimatePresence>
          </ul>
        </>
      )}
    </DemoFrame>
  )
}
