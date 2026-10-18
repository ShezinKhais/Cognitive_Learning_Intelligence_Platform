import { motion } from 'motion/react'

// A half circle of radius 40 from (10, 50) to (90, 50).
const ARC = 'M10 50 A40 40 0 0 1 90 50'
const LENGTH = Math.PI * 40

/**
 * The student's own participation this session: the checkpoints they
 * answered out of those sent. Only they see it. It is not an engagement
 * score, which stays with the lecturer under the fairness rules.
 */
export default function ParticipationGauge({ answered, delivered }: { answered: number; delivered: number }) {
  const share = delivered > 0 ? Math.min(1, answered / delivered) : 0
  return (
    <div className="flex items-center gap-3" title="Only you see this">
      <svg viewBox="0 0 100 56" className="h-12 w-[5.5rem]" role="img" aria-label={`You answered ${answered} of ${delivered} checkpoints`}>
        <path d={ARC} fill="none" stroke="var(--muted)" strokeWidth="9" strokeLinecap="round" />
        <motion.path
          d={ARC}
          fill="none"
          stroke="var(--primary)"
          strokeWidth="9"
          strokeLinecap="round"
          strokeDasharray={LENGTH}
          initial={false}
          animate={{ strokeDashoffset: LENGTH * (1 - share) }}
          transition={{ type: 'spring', stiffness: 120, damping: 20 }}
        />
        <text x="50" y="50" textAnchor="middle" fontSize="19" fontWeight="800" fill="var(--foreground)">
          {delivered > 0 ? `${answered}/${delivered}` : '0'}
        </text>
      </svg>
      <div className="text-sm leading-tight">
        <p className="font-semibold">Your checkpoints</p>
        <p className="text-muted-foreground">Only you see this</p>
      </div>
    </div>
  )
}
