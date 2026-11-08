import { ExternalLink } from 'lucide-react'

import { Wordmark } from '../components/brand/ClipMark'
import { buttonStyles } from '../components/ui/button'
import { useDocumentTitle } from '../components/ui/useDocumentTitle'

// The lecturer and admin tabs in Teams. Both workspaces are built for a full
// browser window, so the tab opens the website instead of squeezing them into
// Teams. In a meeting, the lecturer's controls are in the side panel. Nothing
// here needs a sign-in: the website asks for one itself.
const TARGETS = {
  lecturer: {
    title: 'Lecturer dashboard',
    path: '/lecturer/sessions',
    detail:
      'Upload material, review questions, prepare and run classes, and read the reports. During a Teams meeting, the class controls are also in the C.L.I.P side panel.',
  },
  admin: {
    title: 'Administration',
    path: '/admin',
    detail: 'Accounts, rosters and timetables, data requests, the audit record and system status.',
  },
} as const

export type LauncherTarget = keyof typeof TARGETS

export default function TeamsLauncherPage({ target }: { target: LauncherTarget }) {
  const { title, path, detail } = TARGETS[target]
  useDocumentTitle(title)
  const url = new URL(path, window.location.origin).toString()

  return (
    <main className="grid min-h-screen place-items-center bg-background px-4 py-10">
      <div className="w-full max-w-md">
        <Wordmark />
        <h1 className="mt-8 text-2xl font-bold">{title}</h1>
        <p className="mt-2 text-muted-foreground">{detail}</p>
        <a href={url} target="_blank" rel="noopener noreferrer" className={buttonStyles({ className: 'mt-6' })}>
          Open in your browser
          <ExternalLink size={15} aria-hidden />
        </a>
        <p className="mt-4 text-sm text-muted-foreground">
          Sign in there with your C.L.I.P email and password. Keep this tab to come back to it.
        </p>
      </div>
    </main>
  )
}
