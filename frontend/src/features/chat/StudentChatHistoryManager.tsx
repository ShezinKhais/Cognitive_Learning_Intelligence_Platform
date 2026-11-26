import { useEffect, useState } from 'react'

import {
  deleteAllChatHistory,
  deleteChatExchange,
  listAllChatHistory,
  type SavedChatExchange,
} from './chatHistoryApi'

const PAGE_SIZE = 20

/** Student-owned conversation history. Never mounted on lecturer surfaces. */
export function StudentChatHistoryManager() {
  const [items, setItems] = useState<SavedChatExchange[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE)

  useEffect(() => {
    const abort = new AbortController()
    void listAllChatHistory(abort.signal).then(
      (records) => {
        if (abort.signal.aborted) return
        setItems(records)
        setLoading(false)
      },
      () => {
        if (abort.signal.aborted) return
        setError('Your saved conversations could not be loaded.')
        setLoading(false)
      },
    )
    return () => abort.abort()
  }, [])

  async function removeOne(record: SavedChatExchange) {
    if (busy) return
    if (!window.confirm('Permanently delete this saved conversation?')) return

    setBusy(true)
    setError(null)
    try {
      await deleteChatExchange(record.id)
      // Reload the active chat as well, so a deleted conversation
      // cannot remain visible in the current panel's React state.
      window.location.reload()
    } catch {
      setError('Unable to delete the conversation. Please try again.')
      setBusy(false)
    }
  }

  async function removeAll() {
    if (busy || items.length === 0) return
    if (!window.confirm(
      'Permanently delete ALL your saved chatbot conversations across classes? This cannot be undone.',
    )) return

    setBusy(true)
    setError(null)
    try {
      await deleteAllChatHistory()
      window.location.reload()
    } catch {
      setError('Unable to clear your history. Please try again.')
      setBusy(false)
    }
  }

  return (
    <section
      aria-label="Private student chatbot history"
      className="mt-3 rounded-lg border border-border bg-muted/40 p-3"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold">Your saved conversations</h3>
          <p className="text-xs text-muted-foreground">
            Private to your student account, across your classes.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void removeAll()}
          disabled={loading || busy || items.length === 0}
          className="rounded border border-critical/40 px-3 py-1.5 text-xs text-critical disabled:opacity-50"
        >
          Delete all history
        </button>
      </div>

      {loading && (
        <p role="status" className="mt-3 text-sm">Loading history…</p>
      )}

      {error && (
        <p role="alert" className="mt-3 text-sm text-critical">{error}</p>
      )}

      {!loading && !error && items.length === 0 && (
        <p className="mt-3 text-sm text-muted-foreground">
          No completed conversations have been saved yet.
        </p>
      )}

      {!loading && items.length > 0 && (
        <>
          <p className="mt-3 text-xs text-muted-foreground">
            {items.length} saved exchanges. Most recent first.
          </p>

          <div className="mt-2 max-h-80 space-y-3 overflow-y-auto">
            {items.slice(0, visibleCount).map((record) => (
              <article
                key={record.id}
                className="rounded-lg border border-border bg-card p-3"
              >
                <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                  <span className="text-xs text-muted-foreground">
                    {record.session_id
                      ? `Class ${record.session_id.slice(0, 8)}`
                      : 'Previous class'} · {record.source}
                  </span>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void removeOne(record)}
                    className="text-xs font-medium text-critical underline disabled:opacity-50"
                    aria-label={`Delete saved conversation ${record.id}`}
                  >
                    Delete
                  </button>
                </div>
                <p className="whitespace-pre-wrap break-words text-sm font-semibold">
                  {record.question}
                </p>
                <p className="mt-2 whitespace-pre-wrap break-words text-sm">
                  {record.answer}
                </p>
              </article>
            ))}
          </div>

          {visibleCount < items.length && (
            <button
              type="button"
              onClick={() => setVisibleCount((count) => count + PAGE_SIZE)}
              className="mt-3 rounded-lg border border-border px-3 py-2 text-xs font-medium"
            >
              Show more conversations
            </button>
          )}
        </>
      )}
    </section>
  )
}
