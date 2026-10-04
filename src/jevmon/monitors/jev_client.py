"""Async client for TypeSafe's System One API (Jev): disk cache, raw-response log, retries, leak check.

API (docs.typesafe.ai/api, checked 2 Oct 2026): POST /v1/systemone with {model, state, questions};
the response carries {model, answers, usage}. Limits for jev-1.13.0: 40 requests/s, 100K tokens/s,
64K tokens per request (32K for state + the longest question). Errors: 401, 422, 429, 529.

The client never sees labels. It refuses any state containing label words; the experiment runner
additionally calls `leakguard.find_leaks(state_json, label)` before asking.
"""
from __future__ import annotations

import asyncio
import datetime
import hashlib
import json
import os
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

from ..leakguard import LABEL_WORDS
from ..paths import REPO_ROOT

BASE_URL = "https://api.typesafe.ai/v1"
MODEL = "jev-1.13.0"  # pinned: the jev-latest alias moves when TypeSafe ships a new release
RETRY_STATUSES = {429, 500, 502, 503, 504, 529}
CACHE_DIR = REPO_ROOT / "outputs" / "cache" / "jev"
LOG_DIR = REPO_ROOT / "outputs" / "jev_raw"


class JevError(RuntimeError):
    pass


class LeakError(JevError):
    pass


@dataclass(frozen=True)
class JevResult:
    answers: dict[str, Any]
    model: str  # versioned id that answered, e.g. "jev-1.13.0"
    usage: dict[str, int]
    latency_s: float | None  # None when served from the cache
    cached: bool
    key: str  # sha256 of the canonical request body


def canonical(body: dict) -> str:
    return json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


class JevClient:
    def __init__(
        self,
        api_key: str | None = None,
        model: str = MODEL,
        max_concurrency: int = 8,
        timeout_s: float = 60.0,
        max_attempts: int = 6,
        backoff_base_s: float = 1.0,
        cache_dir: Path | None = CACHE_DIR,
        log_dir: Path | None = LOG_DIR,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        load_dotenv(REPO_ROOT / ".env")
        self.api_key = api_key or os.environ.get("TYPESAFE_API_KEY", "").strip()
        if not self.api_key:
            raise JevError("TYPESAFE_API_KEY is not set (add it to .env in the repo root)")
        self.model = model
        self.max_attempts = max_attempts
        self.backoff_base_s = backoff_base_s
        self.cache_dir = cache_dir
        self.log_dir = log_dir
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._http = httpx.AsyncClient(
            base_url=BASE_URL, timeout=timeout_s, transport=transport,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
        )

    async def __aenter__(self) -> JevClient:
        return self

    async def __aexit__(self, *exc) -> None:
        await self._http.aclose()

    async def ask(self, state: str | dict | list, questions: dict[str, dict], public_text: str | None = None) -> JevResult:
        """Evaluate `questions` against `state`. Identical requests are served from the disk cache.

        `public_text` (the run's public record) exempts label words the agents themselves said in public.
        """
        state_text = state if isinstance(state, str) else canonical({"state": state})
        public = public_text.lower() if public_text is not None else ""
        if leaks := sorted({m.group(0) for m in LABEL_WORDS.finditer(state_text) if m.group(0).lower() not in public}):
            raise LeakError(f"state contains label words {leaks}; refusing to send")

        body = {"model": self.model, "state": state, "questions": questions}
        payload = json.dumps(body, ensure_ascii=False)  # keeps field order (brief before discussion) for Jev
        key = hashlib.sha256(canonical(body).encode()).hexdigest()
        if (hit := self._read_cache(key)) is not None:
            return JevResult(hit["answers"], hit["model"], hit.get("usage", {}), None, True, key)

        async with self._semaphore:
            data, latency = await self._post(payload)
        missing = set(questions) - set(data.get("answers", {}))
        if missing:
            raise JevError(f"response is missing answers for {sorted(missing)}")
        self._write_cache(key, data)
        self._log(key, body, data, latency)
        return JevResult(data["answers"], data["model"], data.get("usage", {}), latency, False, key)

    async def list_models(self) -> list[dict]:
        response = await self._http.get("/models")
        response.raise_for_status()
        return response.json()["models"]

    async def _post(self, payload: str) -> tuple[dict, float]:
        for attempt in range(1, self.max_attempts + 1):
            started = time.perf_counter()
            try:
                response = await self._http.post("/systemone", content=payload.encode())
            except (httpx.TransportError, httpx.TimeoutException) as err:
                if attempt == self.max_attempts:
                    raise JevError(f"request failed after {attempt} attempts: {err!r}") from err
                await asyncio.sleep(self._backoff(attempt, None))
                continue
            latency = time.perf_counter() - started
            if response.status_code == 200:
                return response.json(), latency
            if response.status_code in RETRY_STATUSES and attempt < self.max_attempts:
                await asyncio.sleep(self._backoff(attempt, response.headers.get("retry-after")))
                continue
            raise JevError(f"HTTP {response.status_code}: {response.text[:500]}")
        raise AssertionError("unreachable")

    def _backoff(self, attempt: int, retry_after: str | None) -> float:
        if retry_after:
            try:
                return float(retry_after)
            except ValueError:
                pass
        return self.backoff_base_s * min(2 ** (attempt - 1), 30) * (1 + random.random() / 2)

    def _cache_path(self, key: str) -> Path | None:
        return self.cache_dir / key[:2] / f"{key}.json" if self.cache_dir else None

    def _read_cache(self, key: str) -> dict | None:
        path = self._cache_path(key)
        return json.loads(path.read_text(encoding="utf-8")) if path and path.exists() else None

    def _write_cache(self, key: str, data: dict) -> None:
        if path := self._cache_path(key):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def _log(self, key: str, body: dict, data: dict, latency: float) -> None:
        if not self.log_dir:
            return
        self.log_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.datetime.now(datetime.timezone.utc)
        record = {"key": key, "time": now.isoformat(), "latency_s": round(latency, 4), "request": body, "response": data}
        with (self.log_dir / f"{now.date().isoformat()}.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
