import { Component, type ReactNode } from 'react'

import { ProblemState } from './ui/ProblemState'

// When the page last reloaded itself for a missing chunk. Within a minute of
// that it shows the message instead, so a chunk that is truly gone cannot
// reload the page forever.
const RELOADED_KEY = 'clip_chunk_reload'
const RELOAD_AGAIN_AFTER_MS = 60_000

/** A page's code could not be fetched: a deploy replaced it, or the network
 * dropped. Each browser words it differently. */
function isChunkError(error: unknown): boolean {
  const message = error instanceof Error ? `${error.name} ${error.message}` : String(error)
  return /dynamically imported module|importing a module script|ChunkLoadError|Loading chunk|error loading dynamically/i.test(
    message,
  )
}

type Props = { children: ReactNode; fullScreen?: boolean }
type State = { error: unknown }

/**
 * Catches a page that fails to load or render, so one broken page shows what
 * happened and a way out instead of blanking the whole app. A page whose code
 * went missing after a deploy is reloaded once, quietly, which picks up the
 * new build.
 */
export default class PageErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: unknown): State {
    return { error }
  }

  componentDidCatch(error: unknown): void {
    if (!isChunkError(error)) return
    try {
      const last = Number(window.sessionStorage.getItem(RELOADED_KEY))
      if (Date.now() - last < RELOAD_AGAIN_AFTER_MS) return
      window.sessionStorage.setItem(RELOADED_KEY, String(Date.now()))
    } catch {
      // Storage blocked: no way to tell a first reload from a loop.
      return
    }
    window.location.reload()
  }

  render(): ReactNode {
    const { error } = this.state
    if (error === null) return this.props.children

    const chunk = isChunkError(error)
    const problem = (
      <ProblemState
        fullScreen={this.props.fullScreen}
        art={chunk ? 'offline' : 'page-crash'}
        title={chunk ? 'This page could not load' : 'Something went wrong on this page'}
      >
        {chunk
          ? 'C.L.I.P may have been updated, or the connection dropped. Reloading fetches the latest version.'
          : 'Reload to try again. If it keeps happening, tell your administrator.'}
      </ProblemState>
    )
    return this.props.fullScreen ? problem : <div className="mx-auto max-w-6xl px-5 py-10 sm:px-8">{problem}</div>
  }
}
