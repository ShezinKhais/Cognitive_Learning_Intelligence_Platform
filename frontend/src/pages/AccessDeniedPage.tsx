import { Link } from 'react-router'

export default function AccessDeniedPage() {
  return (
    <main className="min-h-screen grid place-items-center p-8">
      <div className="rounded-xl border border-border bg-card p-6 text-center">
        <h1 className="text-xl font-bold">Access denied</h1>
        <p className="mt-2 text-sm text-muted-foreground">This page requires the administrator role.</p>
        <Link className="mt-4 inline-block underline" to="/">Return home</Link>
      </div>
    </main>
  )
}
