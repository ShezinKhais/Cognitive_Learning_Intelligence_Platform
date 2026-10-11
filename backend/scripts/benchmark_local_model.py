"""Load tests the local model without GuideLLM.

Not a test. The fallback for when GuideLLM cannot run against Ollama (see
docs/local-model-benchmark.md). It sends the prompts written by
scripts.build_benchmark_prompts to the model in .env, a few at a time, and
reports what a student waits for: time to the first word, time to the whole
reply, and words per second. Run from backend/:

    python -m scripts.benchmark_local_model
    python -m scripts.benchmark_local_model --concurrency 1 2 4 --requests 12
    python -m scripts.benchmark_local_model --out benchmarks/results.csv

It talks to the model directly, not through the AI gateway, so the numbers
are the model's own and not the gateway's queue.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import statistics
import time
from dataclasses import astuple, dataclass, fields
from pathlib import Path

from openai import AsyncOpenAI

from app.core.config import get_settings
from scripts.build_benchmark_prompts import DEFAULT_OUT as DEFAULT_PROMPTS


@dataclass
class Sample:
    concurrency: int
    first_token_s: float | None
    total_s: float
    output_tokens: int
    error: str | None = None


def load_prompts(path: Path) -> list[dict]:
    if not path.exists():
        raise SystemExit(f"{path} not found: run python -m scripts.build_benchmark_prompts first")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


async def one_request(client: AsyncOpenAI, model: str, item: dict, concurrency: int) -> Sample:
    started = time.monotonic()
    first = None
    tokens = 0
    try:
        stream = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": item["prompt"]}],
            max_tokens=item.get("output_tokens_count"),
            stream=True,
            stream_options={"include_usage": True},
        )
        pieces = 0
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                first = first or time.monotonic() - started
                pieces += 1
            if chunk.usage:
                tokens = chunk.usage.completion_tokens
        # An older Ollama sends no usage: one piece is about one token.
        tokens = tokens or pieces
    except Exception as exc:  # noqa: BLE001 - a failed request is a result here
        return Sample(concurrency, None, time.monotonic() - started, 0, type(exc).__name__)
    return Sample(concurrency, first, time.monotonic() - started, tokens)


async def run_level(
    client: AsyncOpenAI, model: str, prompts: list[dict], concurrency: int, requests: int
) -> tuple[list[Sample], float]:
    queue = [prompts[n % len(prompts)] for n in range(requests)]
    samples: list[Sample] = []

    async def worker() -> None:
        while queue:
            samples.append(await one_request(client, model, queue.pop(0), concurrency))

    started = time.monotonic()
    await asyncio.gather(*(worker() for _ in range(concurrency)))
    return samples, time.monotonic() - started


def p95(values: list[float]) -> float:
    return statistics.quantiles(values, n=20)[-1] if len(values) > 1 else values[0]


def report(concurrency: int, samples: list[Sample], wall_s: float) -> None:
    ok = [s for s in samples if s.error is None]
    failed = len(samples) - len(ok)
    if not ok:
        print(f"{concurrency:>5}  all {failed} requests failed: {samples[0].error}")
        return
    firsts = [s.first_token_s for s in ok if s.first_token_s is not None] or [0.0]
    totals = [s.total_s for s in ok]
    tokens = sum(s.output_tokens for s in ok)
    print(
        f"{concurrency:>5}  {statistics.median(firsts):>8.2f}  {p95(firsts):>8.2f}"
        f"  {statistics.median(totals):>8.2f}  {p95(totals):>8.2f}"
        f"  {tokens / wall_s:>9.1f}  {len(ok) / wall_s:>7.2f}  {failed:>6}"
    )


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--prompts", type=Path, default=DEFAULT_PROMPTS)
    parser.add_argument("--concurrency", type=int, nargs="+", default=[1, 2, 4])
    parser.add_argument("--requests", type=int, default=8, help="per concurrency level")
    parser.add_argument("--out", type=Path, help="also write every request to this CSV")
    args = parser.parse_args()

    settings = get_settings()
    prompts = load_prompts(args.prompts)
    client = AsyncOpenAI(base_url=settings.ollama_base_url, api_key="ollama")
    print(f"model: {settings.ollama_model}   at: {settings.ollama_base_url}")

    print("warming up (the first call can include loading the model)...")
    warm = await one_request(client, settings.ollama_model, prompts[0], 1)
    if warm.error:
        raise SystemExit(f"the model did not answer: {warm.error}. Is Ollama running?")
    print(f"warm-up took {warm.total_s:.1f}s\n")

    print("                first word (s)      whole reply (s)")
    print("users    median      p95    median      p95   tokens/s   reqs/s  failed")
    everything: list[Sample] = []
    for level in args.concurrency:
        samples, wall_s = await run_level(
            client, settings.ollama_model, prompts, level, max(args.requests, level)
        )
        report(level, samples, wall_s)
        everything += samples

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([field.name for field in fields(Sample)])
            writer.writerows(astuple(s) for s in everything)
        print(f"\nwrote {len(everything)} rows to {args.out}")


if __name__ == "__main__":
    asyncio.run(main())
