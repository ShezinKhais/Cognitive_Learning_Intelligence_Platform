#!/usr/bin/env bash
# Load tests the local Ollama model with GuideLLM. See docs/local-model-benchmark.md.
#
# Run from backend/:  ./scripts/run_guidellm.sh
# Change the model or server with:  OLLAMA_MODEL=llama3.2 OLLAMA_HOST=http://localhost:11434 ./scripts/run_guidellm.sh
# GUIDELLM=/path/to/guidellm uses a GuideLLM installed somewhere not on PATH.
set -euo pipefail

MODEL="${OLLAMA_MODEL:-qwen2.5}"
HOST="${OLLAMA_HOST:-http://localhost:11434}"
GUIDELLM="${GUIDELLM:-guidellm}"
OUT="benchmarks/$(date +%Y%m%d-%H%M%S)-${MODEL//[:\/]/-}"

python -m scripts.build_benchmark_prompts
mkdir -p "$OUT"

# Ollama has no /health route, which GuideLLM checks before it starts, so the
# check is pointed at /v1/models. "target" is the server without /v1.
"$GUIDELLM" run \
  --backend "{\"kind\":\"openai_http\",\"target\":\"$HOST\",\"model\":\"$MODEL\",\"request_format\":\"/v1/chat/completions\",\"api_routes\":{\"/health\":\"v1/models\"}}" \
  --data kind=json_file,path=benchmarks/prompts.jsonl \
  --profile kind=concurrent,streams=1 \
  --override profile.streams 1,2,4 \
  --constraint kind=max_requests,count=12 \
  --constraint kind=max_errors,count=3 \
  --output kind=console \
  --output "kind=json,path=$OUT/results.json" \
  --output "kind=csv,path=$OUT/results.csv" \
  --output "kind=html,path=$OUT/report.html"

echo "Results in $OUT (open report.html in a browser)"
