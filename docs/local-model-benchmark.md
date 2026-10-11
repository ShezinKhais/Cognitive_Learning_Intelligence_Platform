# Load testing the local model

How fast does our model answer when a whole class asks at once? This page
measures it with [GuideLLM](https://github.com/vllm-project/guidellm), as Ms
Asma asked, and has a fallback script for when GuideLLM will not run against
Ollama.

Both tools send the **real classifier prompt** for the forty hand-labelled
answers in `backend/tests/eval`, so the numbers describe the work the model
does in a live class, not random text.

## What the numbers mean

| Number | In plain words | Why we care |
|---|---|---|
| TTFT (time to first token) | How long until the first word appears. | What a student feels as "is it working?". |
| Request latency | How long until the whole reply is done. | A classification is only usable once complete. |
| Output tokens per second | How many words the model writes per second, all users together. | The model's total speed. |
| Requests per second | Replies finished per second. | How many students we can serve. |
| `concurrent@N` | N students asking at the same moment. | We test 1, 2 and 4. |

If the first word takes longer than `AI_FIRST_TOKEN_TIMEOUT_SECONDS` (30 s) or
the whole reply longer than `AI_REQUEST_TIMEOUT_SECONDS` (60 s) at some level,
the gateway would give up at that level. That is the result to report.

## Option 1: GuideLLM

Needs Ollama running with the model from `.env` (`ollama pull qwen2.5`).

```bash
pipx install guidellm         # or: python -m venv ~/guidellm && ~/guidellm/bin/pip install guidellm
cd backend
./scripts/run_guidellm.sh
```

On Windows, run it from Git Bash or WSL. Another model:
`OLLAMA_MODEL=llama3.2 ./scripts/run_guidellm.sh`.

Results land in `backend/benchmarks/<date>-<model>/`: `report.html` (open it in
a browser), `results.csv` and `results.json`. The folder is not committed.

### Why GuideLLM fails against Ollama out of the box, and the fixes

GuideLLM is written for vLLM. Three differences matter, and the script
already handles them:

1. **No `/health` route.** GuideLLM checks `GET /health` before it starts.
   Ollama answers 404, and GuideLLM stops with
   `Client error '404 Not Found' for url 'http://localhost:11434/health'`.
   The script points the check at `/v1/models`, which Ollama has, with
   `"api_routes":{"/health":"v1/models"}`. Another way is to switch the
   check off: `--backend kind=openai_http,...,validate_backend=false`.
   (In GuideLLM 0.8 `validate_backend` only takes true or false, so
   `validate_backend=/v1/models` is refused.)
2. **The target has no `/v1`.** GuideLLM adds `/v1/chat/completions` itself, so
   the target is `http://localhost:11434`, not the `OLLAMA_BASE_URL` in
   `.env`.
3. **The model name is Ollama's**, as `ollama list` shows it (`qwen2.5`), not a
   Hugging Face name.

If the token columns show 0, Ollama is too old to report token counts while
streaming. Update Ollama, or let GuideLLM count them itself by adding
`--tokenizer kind=huggingface_auto,model=Qwen/Qwen2.5-7B-Instruct` to the
command (it downloads the tokenizer once).

GuideLLM 0.8 changed its command line: options are now `kind=...,key=value`,
and older guides that show `guidellm benchmark --target ...` no longer work.

## Option 2: the fallback script

If GuideLLM still will not run, this measures the same things with the
`openai` package the backend already uses, at the `OLLAMA_BASE_URL` in `.env`:

```bash
cd backend
python -m scripts.build_benchmark_prompts
python -m scripts.benchmark_local_model
python -m scripts.benchmark_local_model --concurrency 1 2 4 8 --requests 12 --out benchmarks/results.csv
```

```
                first word (s)      whole reply (s)
users    median      p95    median      p95   tokens/s   reqs/s  failed
    1      ...
```

Other off-the-shelf tools that work with Ollama, if a third opinion is
wanted: [`ollama-benchmark`](https://github.com/aidatatools/ollama-benchmark)
(one user at a time only) and `llama-bench` from llama.cpp (raw model speed,
no HTTP).

## Getting fair numbers

- Close other heavy programs, and run each test twice: the first run can
  include loading the model.
- Ollama answers a few requests at once and queues the rest
  (`OLLAMA_NUM_PARALLEL`). Above that, adding users makes everyone slower
  without more replies per second. That point is the number to put in
  `AI_MAX_CONCURRENCY`.
- Write down the machine (CPU, RAM, GPU), the model and the Ollama version
  with every result.
