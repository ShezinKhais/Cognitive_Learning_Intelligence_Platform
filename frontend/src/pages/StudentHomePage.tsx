export default function StudentHomePage() {
  return (
    <main className="min-h-screen bg-background px-6 py-10">
      <section className="mx-auto max-w-4xl">
        <p className="text-sm font-medium text-info">
          Student workspace
        </p>

        <h1 className="mt-2 text-3xl font-bold">
          Welcome to C.L.I.P
        </h1>

        <p className="mt-2 max-w-2xl text-muted-foreground">
          Your student learning sessions will appear here.
        </p>

        <div className="mt-8 rounded-xl border border-border bg-card p-6">
          <h2 className="text-lg font-semibold">
            Phase 1 preview
          </h2>

          <p className="mt-2 text-sm text-muted-foreground">
            This interface currently uses mock student data while
            the session backend is under development.
          </p>
        </div>
      </section>
    </main>
  )
}