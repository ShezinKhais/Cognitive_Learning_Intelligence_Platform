import { DoorOpen, Undo2 } from 'lucide-react'

/** The room the lecturer put this student in, or that the rooms are closed.
 * C.L.I.P cannot move anyone in Teams: this says where to go. */
export default function AssignedRoom({ label }: { label: string | null }) {
  return (
    <section
      role="status"
      aria-live="polite"
      className="mt-5 flex items-start gap-3 rounded-lg border border-info/30 bg-info/10 px-4 py-3"
    >
      {label === null ? (
        <>
          <Undo2 aria-hidden size={20} className="mt-0.5 shrink-0 text-info" />
          <div>
            <h2 className="font-semibold">Breakout rooms are closed</h2>
            <p className="text-sm text-muted-foreground">Go back to the main meeting if Teams has not moved you already.</p>
          </div>
        </>
      ) : (
        <>
          <DoorOpen aria-hidden size={20} className="mt-0.5 shrink-0 text-info" />
          <div className="min-w-0">
            <h2 className="font-semibold break-words">Your breakout room: {label}</h2>
            <p className="text-sm text-muted-foreground">
              Join {label} in Teams when your lecturer opens the rooms.
            </p>
          </div>
        </>
      )}
    </section>
  )
}
