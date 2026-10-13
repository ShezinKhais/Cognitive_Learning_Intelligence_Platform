import {
  BookOpen,
  CircleStop,
  MessageCircleQuestion,
  Send,
  Sparkles,
} from 'lucide-react'
import {
  type FormEvent,
  useEffect,
  useRef,
} from 'react'

import { MAX_CHAT_QUESTION_LENGTH } from './chatApi'
import type { ChatExchange } from './chatTypes'
import { useSocraticChat } from './useSocraticChat'

const STARTERS = [
  'Can you help me understand the main idea from this session?',
  'Ask me a question that checks my understanding.',
  'Can you give me a hint about the topic we just covered?',
]

export function SocraticChatPanel({
  sessionId,
  compact = false,
}: {
  sessionId: string
  compact?: boolean
}) {
  const {
    state,
    setDraft,
    submit,
    cancel,
    askFollowUp,
    clearError,
  } = useSocraticChat(sessionId)
  const end = useRef<HTMLDivElement>(null)
  const active = Boolean(state.activeId)

  useEffect(() => {
    end.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [state.exchanges])

  function onSubmit(event: FormEvent) {
    event.preventDefault()
    void submit()
  }

  return (
    <section
      aria-labelledby="socratic-chat-heading"
      className={`mx-auto flex w-full flex-col ${compact ? 'min-h-[36rem]' : 'min-h-[42rem]'} rounded-xl border border-border bg-card shadow-[var(--shadow-card)]`}
    >
      <header className="border-b border-border p-4 sm:p-5">
        <div className="flex items-center gap-3">
          <span className="grid size-10 place-items-center rounded-full bg-secondary text-info">
            <Sparkles aria-hidden="true" size={20} />
          </span>
          <div>
            <h2 id="socratic-chat-heading" className="font-semibold">
              Socratic learning assistant
            </h2>
            <p className="text-sm text-muted-foreground">
              Guided hints grounded in your lecturer’s material
            </p>
          </div>
        </div>
        <p className="mt-3 rounded-lg bg-muted px-3 py-2 text-xs text-muted-foreground">
          This assistant helps you reason through a topic. It will guide you instead of giving a final answer.
        </p>
      </header>

      <div
        className="flex-1 space-y-5 overflow-y-auto p-4 sm:p-5"
        aria-live="polite"
        aria-busy={active}
      >
        {state.exchanges.length === 0 ? (
          <ChatWelcome onSelect={(prompt) => void submit(prompt)} />
        ) : (
          state.exchanges.map((exchange) => (
            <Exchange
              key={exchange.id}
              exchange={exchange}
              onFollowUp={askFollowUp}
              disabled={active}
            />
          ))
        )}

        {state.error && (
          <div role="alert" className="rounded-lg border border-critical/30 p-4 text-sm">
            <p className="font-semibold text-critical">The assistant is unavailable</p>
            <p className="mt-1 text-muted-foreground">{state.error}</p>
            <button
              type="button"
              onClick={clearError}
              className="mt-2 font-medium text-info hover:underline"
            >
              Dismiss
            </button>
          </div>
        )}
        <div ref={end} />
      </div>

      <form onSubmit={onSubmit} className="border-t border-border p-4">
        <label htmlFor="chat-question" className="sr-only">
          Ask about this session
        </label>
        <textarea
          id="chat-question"
          value={state.draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault()
              event.currentTarget.form?.requestSubmit()
            }
          }}
          maxLength={MAX_CHAT_QUESTION_LENGTH}
          rows={compact ? 2 : 3}
          disabled={active}
          placeholder="Ask for a hint or help understanding a concept…"
          className="w-full resize-none rounded-lg border border-border bg-input-background px-3 py-3 text-sm outline-none focus:ring-2 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-60"
        />
        <div className="mt-2 flex items-center justify-between gap-3">
          <span className="text-xs text-muted-foreground">
            {state.draft.length}/{MAX_CHAT_QUESTION_LENGTH}
          </span>
          {active ? (
            <button
              type="button"
              onClick={cancel}
              disabled={state.phase === 'cancelling'}
              className="inline-flex items-center gap-2 rounded-lg border border-critical px-4 py-2 text-sm font-semibold text-critical disabled:opacity-60"
            >
              <CircleStop aria-hidden="true" size={17} />
              {state.phase === 'cancelling' ? 'Stopping…' : 'Stop response'}
            </button>
          ) : (
            <button
              type="submit"
              disabled={!state.draft.trim()}
              className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Send aria-hidden="true" size={17} />
              Ask
            </button>
          )}
        </div>
      </form>
    </section>
  )
}

function ChatWelcome({ onSelect }: { onSelect: (prompt: string) => void }) {
  return (
    <div className="py-6 text-center">
      <MessageCircleQuestion aria-hidden="true" className="mx-auto text-info" size={34} />
      <h3 className="mt-3 font-semibold">What would you like to explore?</h3>
      <p className="mx-auto mt-2 max-w-md text-sm text-muted-foreground">
        Ask about this class and the assistant will use the linked lecture material to guide you.
      </p>
      <div className="mx-auto mt-5 grid max-w-lg gap-2 text-left">
        {STARTERS.map((prompt) => (
          <button
            key={prompt}
            type="button"
            onClick={() => onSelect(prompt)}
            className="rounded-lg border border-border p-3 text-sm hover:bg-muted focus:outline-none focus:ring-2 focus:ring-ring"
          >
            {prompt}
          </button>
        ))}
      </div>
    </div>
  )
}

function Exchange({
  exchange,
  onFollowUp,
  disabled,
}: {
  exchange: ChatExchange
  onFollowUp: (prompt: string) => void
  disabled: boolean
}) {
  return (
    <article className="space-y-3">
      <div className="ml-auto max-w-[88%] rounded-2xl rounded-br-sm bg-primary px-4 py-3 text-sm text-primary-foreground">
        {exchange.question}
      </div>
      <div className="max-w-[94%] rounded-2xl rounded-bl-sm bg-muted px-4 py-3 text-sm">
        {exchange.answer ? (
          <p className="whitespace-pre-wrap leading-6">{exchange.answer}</p>
        ) : exchange.phase === 'streaming' ? (
          <p className="text-muted-foreground">Thinking through the lecture material…</p>
        ) : null}

        {exchange.phase === 'cancelled' && (
          <StateNote title="Response stopped" detail={exchange.explanation} />
        )}
        {exchange.phase === 'unsupported' && (
          <StateNote title="I can’t help with that request" detail={exchange.explanation} />
        )}
        {exchange.phase === 'empty-retrieval' && (
          <StateNote title="No matching lecture material" detail={exchange.explanation} />
        )}
        {exchange.phase === 'failed' && (
          <StateNote title="Response interrupted" detail="Please try asking again." />
        )}

        {exchange.citations.length > 0 && (
          <div className="mt-4 border-t border-border pt-3">
            <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              <BookOpen aria-hidden="true" size={15} /> Sources
            </p>
            <ul className="mt-2 space-y-2">
              {exchange.citations.map((citation) => {
                const location = citation.source_slide !== null
                  ? `Slide ${citation.source_slide}`
                  : citation.source_page !== null
                    ? `Page ${citation.source_page}`
                    : 'Lecture material'
                return (
                  <li key={citation.id} className="rounded-lg border border-border bg-card p-3">
                    <p className="text-xs font-semibold">{citation.material_title} · {location}</p>
                    {citation.excerpt && (
                      <p className="mt-1 text-xs leading-5 text-muted-foreground">{citation.excerpt}</p>
                    )}
                  </li>
                )
              })}
            </ul>
          </div>
        )}
      </div>

      {exchange.followUps.length > 0 && exchange.phase === 'completed' && (
        <div className="flex flex-wrap gap-2 pl-2">
          {exchange.followUps.map((prompt) => (
            <button
              key={prompt}
              type="button"
              disabled={disabled}
              onClick={() => onFollowUp(prompt)}
              className="rounded-full border border-info/30 px-3 py-1.5 text-xs font-medium text-info hover:bg-muted disabled:opacity-50"
            >
              {prompt}
            </button>
          ))}
        </div>
      )}
    </article>
  )
}

function StateNote({ title, detail }: { title: string; detail: string | null }) {
  return (
    <div className="mt-2">
      <p className="font-semibold">{title}</p>
      {detail && <p className="mt-1 text-muted-foreground">{detail}</p>}
    </div>
  )
}
