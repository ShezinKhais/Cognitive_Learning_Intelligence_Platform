"""Manual check: does the real model produce questions that pass validation?

Not a test. Needs Ollama running, and exists to calibrate GROUNDING_THRESHOLD
against real output rather than a guessed number.
"""

import asyncio

from openai import AsyncOpenAI

from app.core.config import get_settings
from app.services.generation import build_prompt, parse_drafts, rejection_reasons
from app.services.retrieval import RetrievedChunk

CHUNKS = [
    RetrievedChunk(
        chunk_id=None,
        chunk_index=0,
        chunk_text=(
            "Transfer learning reuses a network trained on a large dataset. "
            "The base layers are frozen so their weights do not change during "
            "training, and only the final classification layer is retrained on "
            "the new task."
        ),
        source_page=3,
        distance=0.1,
    )
]


async def main():
    settings = get_settings()
    client = AsyncOpenAI(base_url=settings.ollama_base_url, api_key="ollama")

    response = await client.chat.completions.create(
        model=settings.ollama_model,
        messages=[{"role": "user", "content": build_prompt(CHUNKS, count=3)}],
    )
    raw = response.choices[0].message.content or ""
    print("=== RAW MODEL OUTPUT ===")
    print(raw)

    drafts = parse_drafts(raw)
    print(f"\n=== {len(drafts)} DRAFTS ===")
    for draft in drafts:
        reasons = rejection_reasons(draft, CHUNKS)
        status = "ACCEPTED" if not reasons else f"REJECTED: {'; '.join(reasons)}"
        print(f"\n{status}")
        print(f"  {draft.prompt}")
        print(f"  excerpt: {draft.source_excerpt!r}")


asyncio.run(main())
