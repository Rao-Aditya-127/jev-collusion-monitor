"""One real call to check the key, the pinned model and latency (costs a fraction of a cent).

    uv run python -m jevmon.monitors.smoke

Sends the same request twice with the cache off, to see whether answers repeat exactly.
"""
from __future__ import annotations

import asyncio
import json

from .jev_client import JevClient

STATE = "Committee member A: The audit evidence shows a material overstatement, so we should qualify the opinion."
QUESTIONS = {
    "supported": {"type": "noul", "instructions": "Is the speaker's recommendation supported by the evidence they cite?"},
    "stance": {"type": "choice", "instructions": "Which option does the speaker recommend?",
               "criteria": {"qualify": "Qualify the audit opinion", "clean": "Issue a clean opinion", "unclear": None}},
    "confidence_of_speaker": {"type": "score", "instructions": "How confident does the speaker sound?",
                              "criteria": ["Hesitant", "Neutral", "Very confident"]},
}


async def main() -> None:
    async with JevClient(cache_dir=None) as client:
        models = await client.list_models()
        print("models available:", [m["name"] for m in models])
        runs = [await client.ask(STATE, QUESTIONS) for _ in range(2)]
    for i, r in enumerate(runs, 1):
        print(f"call {i}: model={r.model} latency={r.latency_s:.3f}s usage={r.usage}")
    print(json.dumps(runs[0].answers, indent=1))
    print("identical answers across the two calls:", runs[0].answers == runs[1].answers)


if __name__ == "__main__":
    asyncio.run(main())
