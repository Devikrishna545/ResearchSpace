

async def test_fan_out_enforces_per_source_deadline():
    """Regression: httpx per-operation timeouts let slow sources run ~10s; the registry must bound them."""
    import asyncio, time
    from app.shared.schemas.common import HealthStatus
    from app.modules.discovery.schemas import SearchPlan, SearchFilters
    from app.modules.discovery.providers.registry import SourceRegistry

    class SlowAdapter:
        name = "slow"
        async def search(self, query):
            await asyncio.sleep(30)
            return ["never"]

    class FastAdapter:
        name = "fast"
        async def search(self, query):
            return ["ok"]

    from app.core.config import get_settings
    get_settings.cache_clear()
    import os
    os.environ["SOURCE_TIMEOUT_S"] = "0.3"
    try:
        get_settings.cache_clear()
        registry = SourceRegistry([SlowAdapter(), FastAdapter()])
        plan = SearchPlan(topic="t", sub_queries=["t"], filters=SearchFilters())
        start = time.perf_counter()
        results = await registry.fan_out(plan)
        elapsed = time.perf_counter() - start
        assert elapsed < 3, f"fan-out was not bounded: {elapsed:.1f}s"
        assert results == ["ok"]  # fast source still returns partial results
        slow = next(h for h in registry.health if h.source == "slow")
        assert slow.status == HealthStatus.DEGRADED and "timed out" in (slow.error or "")
    finally:
        os.environ.pop("SOURCE_TIMEOUT_S", None)
        get_settings.cache_clear()
