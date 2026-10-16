import { AnimatePresence, motion } from 'motion/react'

import { Panel, Tag, type Tone } from '../../components/ui/primitives'
import { ACTIVITY_LABEL, describeSilence, type RoomActivity, type RoomStatus } from './rooms'

const TONE: Record<RoomActivity, Tone> = {
  active: 'good',
  quiet: 'mixed',
  needs_attention: 'poor',
  unknown: 'neutral',
}

/**
 * Breakout rooms during a live session: which rooms are talking and which
 * have gone quiet. Built from voice-activity counts and answers only, never
 * audio or what is said. Hidden until a student confirms a room.
 */
export default function RoomsPanel({ rooms }: { rooms: readonly RoomStatus[] }) {
  if (rooms.length === 0) return null
  return (
    <Panel
      title="Breakout rooms"
      description="From when students speak and answer, never what they say."
      className="lg:col-span-2"
    >
      <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        <AnimatePresence initial={false}>
          {rooms.map((room) => (
            <motion.li
              key={room.room_label}
              layout
              initial={{ opacity: 0, scale: 0.98 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.18 }}
              className={`rounded-md border px-4 py-3 ${
                room.status === 'needs_attention' ? 'border-critical/40 bg-critical/5' : 'border-border'
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="truncate font-bold">{room.room_label}</span>
                <Tag tone={TONE[room.status]}>{ACTIVITY_LABEL[room.status]}</Tag>
              </div>
              <p className="mt-1 text-sm text-muted-foreground">
                {room.members} {room.members === 1 ? 'student' : 'students'}
                {room.speaking_now > 0 ? `, ${room.speaking_now} speaking` : `, ${describeSilence(room.silence_seconds).toLowerCase()}`}
                {room.task_interactions > 0 && `, ${room.task_interactions} ${room.task_interactions === 1 ? 'answer' : 'answers'}`}
              </p>
            </motion.li>
          ))}
        </AnimatePresence>
      </ul>
    </Panel>
  )
}
