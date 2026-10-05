# The AI gateway

Owner: General CS, Phase 5. Code: `backend/app/services/ai_gateway.py`.

Every call to the language model goes through the gateway. It exists so that AI
work cannot slow down or block a live session, and so that each workstream gets
queueing, deadlines, retries, cancellation and a fallback without writing them.

If you are adding a model call in Phase 5 (classification, the chatbot,
recommendations), call the gateway. Do not create your own `AsyncOpenAI` client
for chat completions: a call made around the gateway skips the queue and competes
with every student in a live class.

## What it does for you

| Concern | Behaviour |
|---|---|
| Concurrency | At most `AI_MAX_CONCURRENCY` calls reach the model at once. |
| Queue | The rest wait by priority, then by arrival. A full queue refuses at once, and a call that waits longer than `AI_QUEUE_TIMEOUT_SECONDS` gives up. |
| Deadlines | Each attempt is timed. A stream is timed to its first piece, between pieces and overall. |
| Retries | A call that could not reach the model is retried with a growing pause. A stream is only retried before its first piece. |
| Circuit breaker | After several failures in a row the model is left alone for a cool-down and calls are refused at once. |
| Fallback | A fallback model is tried once if configured. A request with `fallback` text gets that text back in place of an error. |
| Cancellation | Cancelling a call or leaving a stream closes the connection to the model and frees the slot, including while queued. |
| Warm-up | The model is loaded in the background at startup. A cold load took 33 seconds on a development laptop. |

## Priorities

Pick the one that matches who is waiting.

| Priority | Use for |
|---|---|
| `Priority.LIVE` | A student or lecturer in a running session: the chatbot, classifying a live answer. |
| `Priority.INTERACTIVE` | Someone is looking at the screen, outside a session. The default. |
| `Priority.BACKGROUND` | Nobody is watching: material processing. |

## One reply

```python
from app.services.ai_gateway import AiRequest, Priority, get_ai_gateway

result = await get_ai_gateway().complete(
    AiRequest(
        messages=[{"role": "user", "content": prompt}],
        purpose="classification",      # appears in the log
        priority=Priority.LIVE,
        fallback=None,                 # or text to return if the model cannot answer
    )
)
result.text       # the reply
result.model      # the model that wrote it: store this with the result
result.fallback   # True when the text is your fallback and no model wrote it
```

Without `fallback`, a failure raises `AiUnavailableError`. It is a 503 with code
`AI_UNAVAILABLE`, so a route that does not catch it still answers cleanly. The
more specific kinds are `AiBusyError` (`AI_BUSY`), `AiRejectedError`
(`AI_REJECTED`, the request itself was refused, so do not send it again) and
`AiInterruptedError` (`AI_INTERRUPTED`, streams only).

## A reply as it is written

```python
async with get_ai_gateway().stream(request) as reply:
    async for text in reply:
        await send_to_student(text)

reply.text        # everything delivered
reply.model
reply.cancelled   # True if reply.cancel() ended it
reply.fallback
```

- Leaving the `async with` block stops the model, however the block is left.
- `reply.cancel()` can be called from another task, such as the one that
  receives a "stop" message from the student. The loop then ends normally.
- If the model stops partway, the loop raises `AiInterruptedError`. The pieces
  already sent stay sent, so tell the student the reply was cut short.
- With `fallback` set and nothing delivered yet, the loop yields the fallback
  text once and `reply.fallback` is true.

## What it does not do

- It does not write prompts, check replies or store anything. Guardrails, the
  direct-answer restriction and persistence belong to the workstreams that call it.
- It never logs a prompt or a reply, because they contain students' own words.
  It logs purpose, priority, outcome, model, attempts and duration.
- It has no HTTP route or WebSocket event of its own. How a streamed reply
  reaches the browser is a contract change and needs the group's agreement.
- Embeddings do not go through it. They use a different model and run only
  during material processing.

## Settings

All are in `backend/app/core/config.py` and can be set in `backend/.env`.

| Setting | Default | Meaning |
|---|---|---|
| `AI_MAX_CONCURRENCY` | 2 | Calls sent to the model at once. Match Ollama's `OLLAMA_NUM_PARALLEL`. |
| `AI_QUEUE_LIMIT` | 32 | Calls allowed to wait. |
| `AI_QUEUE_TIMEOUT_SECONDS` | 20 | How long a call may wait for a slot. |
| `AI_REQUEST_TIMEOUT_SECONDS` | 60 | One attempt at a whole reply. |
| `AI_FIRST_TOKEN_TIMEOUT_SECONDS` | 30 | A stream's first piece. |
| `AI_STREAM_IDLE_TIMEOUT_SECONDS` | 15 | The gap between a stream's pieces. |
| `AI_STREAM_TIMEOUT_SECONDS` | 120 | A whole streamed reply. |
| `AI_MAX_ATTEMPTS` | 3 | Attempts at the configured model. |
| `AI_RETRY_PAUSE_SECONDS` | 0.5 | Pause before the second attempt. It doubles after that. |
| `AI_BREAKER_FAILURES` | 5 | Failures in a row before calls are refused. |
| `AI_BREAKER_COOLDOWN_SECONDS` | 30 | How long they are refused for. |
| `AI_WARMUP_ENABLED` | true | Load the model at startup. |
| `AI_WARMUP_TIMEOUT_SECONDS` | 120 | One warm-up attempt. |
| `OLLAMA_FALLBACK_MODEL` | empty | A second model, tried once when the first cannot answer. |

`AiRequest` can override the attempt timeout, the number of attempts and the
queue wait for one call. Question generation does: it waits up to ten minutes
for its turn, since nobody is watching it.

## Testing your code against it

Build a gateway around a fake model. Nothing needs Ollama.

```python
from app.services.ai_gateway import AiGateway

class FakeModel:
    async def complete(self, model, messages, *, max_tokens):
        return "Partial"

    async def stream(self, model, messages, *, max_tokens):
        yield "Think about "
        yield "light."

gateway = AiGateway(FakeModel(), "test-model")
```

`backend/tests/test_ai_gateway.py` has a fuller fake that can fail, hang and
break partway. To see the real behaviour, with Ollama running:

```
cd backend
python scripts/try_ai_gateway.py
```
