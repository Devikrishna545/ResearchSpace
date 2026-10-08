import asyncio

import httpx
import pytest

from app.shared.schemas.common import HealthStatus
from app.modules.papers.schemas.paper import RawPaperRecord
from app.modules.discovery.schemas import SearchFilters, SearchPlan
from app.modules.discovery.providers.registry import SourceRegistry
from app.platform.cache.source_results import SourceResultCache


def plan(topic="retrieval"):
    return SearchPlan(topic=topic, sub_queries=[topic], filters=SearchFilters(), limit=3)


class Adapter:
    name = "openalex"

    def __init__(self, owner_marker="private-a"):
        self.calls = 0
        self.owner_marker = owner_marker
        self.fail = None

    async def search(self, query):
        self.calls += 1
        if self.fail:
            error = self.fail
            self.fail = None
            raise error
        return [RawPaperRecord(
            title=f"Result for {query.query}", source=self.name,
            raw_payload={"owner_marker": self.owner_marker},
        )]


async def search(adapter, cache, user="member-a", topic="retrieval", limit=3):
    registry = SourceRegistry([adapter], owner_id=user, cache=cache)
    results = await registry.fan_out(plan(topic), limit=limit)
    return results, registry.health[0]


async def test_hit_miss_exact_parameters_and_defensive_record_copies():
    cache = SourceResultCache()
    adapter = Adapter()
    first, health = await search(adapter, cache)
    assert adapter.calls == 1 and not health.cached
    first[0].raw_payload["owner_marker"] = "modified by caller"
    second, health = await search(adapter, cache)
    assert adapter.calls == 1 and health.cached
    assert second[0].raw_payload["owner_marker"] == "private-a"
    await search(adapter, cache, topic="different topic")
    await search(adapter, cache, limit=5)
    assert adapter.calls == 3
    assert len(cache) == 3


async def test_cache_is_scoped_to_member_even_if_result_contains_private_data():
    cache = SourceResultCache()
    first_adapter, second_adapter = Adapter("contact-for-a"), Adapter("contact-for-b")
    a, _ = await search(first_adapter, cache, user="member-a")
    b, _ = await search(second_adapter, cache, user="member-b")
    again, health = await search(first_adapter, cache, user="member-a")
    assert first_adapter.calls == second_adapter.calls == 1
    assert a[0].raw_payload["owner_marker"] == again[0].raw_payload["owner_marker"] == "contact-for-a"
    assert b[0].raw_payload["owner_marker"] == "contact-for-b"
    assert health.cached
    assert all("contact-for-" not in repr(key) for key in cache._entries)


async def test_expiry_and_both_size_limits():
    now = [0.0]
    cache = SourceResultCache(ttl_seconds=10, max_entries=1, max_bytes=100000, clock=lambda: now[0])
    adapter = Adapter()
    await search(adapter, cache)
    now[0] = 9.9
    assert (await search(adapter, cache))[1].cached
    await search(adapter, cache, topic="another")
    assert len(cache) == 1
    await search(adapter, cache)
    assert adapter.calls == 3
    now[0] = 20
    assert not (await search(adapter, cache))[1].cached
    assert adapter.calls == 4
    bounded = SourceResultCache(ttl_seconds=10, max_entries=1, max_bytes=100, clock=lambda: now[0])
    record = RawPaperRecord(source="test", title="Large", abstract="x" * 300)
    assert not bounded.set(("owner", "test", "query"), [record])
    assert len(bounded) == 0 and bounded.total_bytes == 0


@pytest.mark.parametrize("kind", ["429", "http_timeout", "hard_timeout"])
async def test_error_or_timeout_is_not_cached_and_next_request_retries(kind):
    cache = SourceResultCache()
    adapter = Adapter()
    if kind == "429":
        request = httpx.Request("GET", "https://api.openalex.org/works")
        adapter.fail = httpx.HTTPStatusError(
            "rate limited", request=request,
            response=httpx.Response(429, headers={"Retry-After": "8"}, request=request),
        )
    elif kind == "http_timeout":
        adapter.fail = httpx.ReadTimeout("upstream stalled")
    else:
        adapter.fail = TimeoutError("hard deadline")
    first, health = await search(adapter, cache)
    assert first == [] and not health.cached and len(cache) == 0
    assert health.status == (HealthStatus.RATE_LIMITED if kind == "429" else HealthStatus.DEGRADED)
    second, health = await search(adapter, cache)
    assert adapter.calls == 2 and len(second) == 1 and not health.cached
    assert (await search(adapter, cache))[1].cached


async def test_partial_work_that_raises_is_never_cached():
    class Partial(Adapter):
        async def search(self, query):
            self.calls += 1
            if self.calls == 1:
                _partial = RawPaperRecord(source=self.name, title="Incomplete")
                raise httpx.ReadError("connection dropped")
            return await super().search(query)

    cache = SourceResultCache()
    adapter = Partial()
    first, health = await search(adapter, cache)
    assert first == [] and health.status == HealthStatus.DEGRADED and len(cache) == 0
    second, health = await search(adapter, cache)
    assert len(second) == 1 and not health.cached


async def test_unowned_registry_never_uses_shared_cache():
    cache = SourceResultCache()
    adapter = Adapter()
    registry = SourceRegistry([adapter], cache=cache)
    await registry.fan_out(plan())
    await registry.fan_out(plan())
    assert adapter.calls == 2 and len(cache) == 0
