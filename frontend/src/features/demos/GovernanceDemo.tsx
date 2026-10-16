import { useMemo, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'

import { buttonStyles } from '../../components/ui/button'
import { Tag } from '../../components/ui/primitives'
import DemoFrame from './DemoFrame'

/** Rows per kind of data, with how many days old each batch is. */
const STORED = [
  { table: 'Answers and their marks', batches: [[400, 12], [380, 45], [520, 95], [610, 140], [300, 220]] },
  { table: 'Engagement summaries', batches: [[90, 12], [85, 45], [120, 95], [140, 140], [60, 220]] },
  { table: 'Alerts', batches: [[6, 12], [9, 45], [14, 95], [11, 140], [4, 220]] },
  { table: 'Teams roster snapshots', batches: [[3, 12], [3, 45], [4, 95], [5, 140], [2, 220]] },
] as const

interface Request {
  id: string
  who: string
  what: string
  asked: string
}

const REQUESTS: Request[] = [
  { id: 'r1', who: 'Student in CSIT321', what: 'Delete my answers and engagement from week 4', asked: '2 days ago' },
  { id: 'r2', who: 'Student in CSIT314', what: 'Delete everything stored about me', asked: '5 days ago' },
]

interface Entry {
  at: string
  action: string
  detail: string
}

const START_LOG: Entry[] = [
  { at: '09:02', action: 'Signed in', detail: 'Administrator' },
  { at: '09:05', action: 'Roster imported', detail: 'CSIT321, 24 students matched' },
  { at: '09:40', action: 'Report built', detail: 'Week 7: Threat modelling' },
]

function clock(): string {
  return new Date().toLocaleTimeString('en-AE', { hour: '2-digit', minute: '2-digit', hour12: false })
}

export default function GovernanceDemo() {
  const [days, setDays] = useState(90)
  const [purged, setPurged] = useState<number | null>(null)
  const [requests, setRequests] = useState(REQUESTS)
  const [decided, setDecided] = useState<(Request & { outcome: 'Deleted' | 'Refused' })[]>([])
  const [log, setLog] = useState(START_LOG)

  const expired = useMemo(
    () =>
      STORED.map(({ table, batches }) => ({
        table,
        rows: batches.filter(([, age]) => age > (purged ?? days)).reduce((sum, [rows]) => sum + rows, 0),
      })),
    [days, purged],
  )
  const total = expired.reduce((sum, row) => sum + row.rows, 0)

  function record(action: string, detail: string) {
    setLog((current) => [{ at: clock(), action, detail }, ...current])
  }

  function runPurge() {
    record('Retention purge run', `${total.toLocaleString()} rows older than ${days} days deleted`)
    setPurged(100000)
  }

  function decide(request: Request, outcome: 'Deleted' | 'Refused') {
    setRequests((current) => current.filter((item) => item.id !== request.id))
    setDecided((current) => [{ ...request, outcome }, ...current])
    record(outcome === 'Deleted' ? 'Deletion request approved' : 'Deletion request refused', request.what)
  }

  return (
    <DemoFrame>
      <div className="grid gap-6 lg:grid-cols-2">
        <section>
          <h3 className="text-lg font-bold">Retention</h3>
          <label className="mt-3 block text-sm font-semibold">
            Keep data for <span className="text-primary">{days} days</span>
            <input
              type="range"
              min={30}
              max={365}
              step={15}
              value={days}
              onChange={(event) => {
                setDays(Number(event.target.value))
                setPurged(null)
              }}
              className="mt-2 block w-full accent-[var(--primary)]"
            />
          </label>
          <ul className="mt-4 divide-y divide-border rounded-md border border-border">
            {expired.map((row) => (
              <li key={row.table} className="flex justify-between gap-3 px-4 py-2.5 text-sm">
                <span>{row.table}</span>
                <motion.span key={`${row.table}-${row.rows}`} initial={{ opacity: 0.3 }} animate={{ opacity: 1 }} className="font-semibold">
                  {row.rows.toLocaleString()} past it
                </motion.span>
              </li>
            ))}
          </ul>
          <div className="mt-3 flex items-center gap-3">
            <button type="button" className={buttonStyles({ intent: 'danger' })} disabled={total === 0} onClick={runPurge}>
              Delete {total.toLocaleString()} rows now
            </button>
            {purged !== null && <span className="text-sm text-success">Done. The daily run keeps it this way.</span>}
          </div>
          <p className="mt-2 text-xs text-muted-foreground">The audit log is never purged: it is the record that this ran.</p>
        </section>

        <section>
          <h3 className="text-lg font-bold">Deletion requests</h3>
          <ul className="mt-3 space-y-2">
            <AnimatePresence initial={false}>
              {requests.map((request) => (
                <motion.li
                  key={request.id}
                  layout
                  exit={{ opacity: 0, x: 24 }}
                  transition={{ duration: 0.18 }}
                  className="rounded-md border border-border px-4 py-3"
                >
                  <p className="font-semibold">{request.what}</p>
                  <p className="text-sm text-muted-foreground">
                    {request.who}, asked {request.asked}
                  </p>
                  <div className="mt-2 flex gap-2">
                    <button type="button" className={buttonStyles()} onClick={() => decide(request, 'Deleted')}>
                      Approve and delete
                    </button>
                    <button type="button" className={buttonStyles({ intent: 'quiet' })} onClick={() => decide(request, 'Refused')}>
                      Refuse
                    </button>
                  </div>
                </motion.li>
              ))}
            </AnimatePresence>
            {requests.length === 0 && <li className="text-sm text-muted-foreground">No requests are waiting.</li>}
          </ul>
          {decided.length > 0 && (
            <ul className="mt-3 space-y-1 text-sm">
              {decided.map((request) => (
                <li key={request.id} className="flex items-center justify-between gap-2">
                  <span className="truncate text-muted-foreground">{request.what}</span>
                  <Tag tone={request.outcome === 'Deleted' ? 'good' : 'neutral'}>{request.outcome}</Tag>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      <section className="mt-6 border-t border-border pt-4">
        <h3 className="text-lg font-bold">Audit log</h3>
        <ol className="mt-3 space-y-1.5 text-sm">
          <AnimatePresence initial={false}>
            {log.map((entry, index) => (
              <motion.li
                key={`${entry.at}-${entry.action}-${log.length - index}`}
                initial={{ opacity: 0, y: -6, backgroundColor: 'var(--highlight)' }}
                animate={{ opacity: 1, y: 0, backgroundColor: 'rgba(0,0,0,0)' }}
                transition={{ duration: 0.6 }}
                className="grid grid-cols-[3.5rem_1fr] gap-3 rounded px-2 py-1 sm:grid-cols-[3.5rem_14rem_1fr]"
              >
                <span className="text-muted-foreground">{entry.at}</span>
                <span className="font-semibold">{entry.action}</span>
                <span className="col-start-2 text-muted-foreground sm:col-start-auto">{entry.detail}</span>
              </motion.li>
            ))}
          </AnimatePresence>
        </ol>
      </section>
    </DemoFrame>
  )
}
