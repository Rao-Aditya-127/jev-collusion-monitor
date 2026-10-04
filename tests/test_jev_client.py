"""Offline tests: a fake transport stands in for api.typesafe.ai."""
import asyncio
import json

import httpx
import pytest

from jevmon.monitors.jev_client import MODEL, JevClient, JevError, LeakError

QUESTIONS = {"urgent": {"type": "noul", "instructions": "Does this convey urgency?"}}
OK = {"model": "jev-1.13.0", "answers": {"urgent": {"type": "noul", "noul": 0.9}},
      "usage": {"input_tokens": 10, "output_tokens": 2}}


def _client(tmp_path, handler):
    return JevClient(api_key="test-key", cache_dir=tmp_path / "cache", log_dir=tmp_path / "log",
                     transport=httpx.MockTransport(handler), backoff_base_s=0)


def _ask(tmp_path, handler, state="Help! My payouts have been failing for 3 days.", times=1):
    async def go():
        async with _client(tmp_path, handler) as client:
            return [await client.ask(state, QUESTIONS) for _ in range(times)]
    return asyncio.run(go())


def test_sends_pinned_model_and_serves_repeats_from_cache(tmp_path):
    bodies = []

    def handler(request):
        assert request.url.path == "/v1/systemone"
        assert request.headers["authorization"] == "Bearer test-key"
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=OK)

    first, second = _ask(tmp_path, handler, times=2)
    assert len(bodies) == 1 and bodies[0]["model"] == MODEL == "jev-1.13.0"
    assert not first.cached and second.cached and first.answers == second.answers
    assert first.key == second.key and first.latency_s is not None and second.latency_s is None
    assert len(list((tmp_path / "log").glob("*.jsonl"))) == 1


def test_retries_rate_limit_and_overload(tmp_path):
    responses = iter([httpx.Response(429, headers={"retry-after": "0"}), httpx.Response(529), httpx.Response(200, json=OK)])
    (result,) = _ask(tmp_path, lambda request: next(responses))
    assert result.answers["urgent"]["noul"] == 0.9


def test_validation_error_is_not_retried(tmp_path):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(422, json={"detail": "criteria missing"})

    with pytest.raises(JevError, match="422"):
        _ask(tmp_path, handler)
    assert len(calls) == 1


def test_refuses_state_with_label_words(tmp_path):
    def handler(request):
        raise AssertionError("must not reach the network")

    with pytest.raises(LeakError):
        _ask(tmp_path, handler, state={"history": ["[Ana]: as the colluder I will push B"]})


def test_label_words_already_public_are_allowed(tmp_path):
    said = "[Clive]: no evidence of coordination or collusion beyond the three officers"

    async def go(public):
        async with _client(tmp_path, lambda request: httpx.Response(200, json=OK)) as client:
            return await client.ask({"history": [said]}, QUESTIONS, public_text=public)

    assert asyncio.run(go(said)).answers["urgent"]["noul"] == 0.9
    with pytest.raises(LeakError):
        asyncio.run(go("something else entirely"))
