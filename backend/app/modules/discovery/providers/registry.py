import asyncio
import json
import math
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import httpx
from app.core.config import get_settings
from app.shared.schemas.common import HealthStatus, SourceHealth
from app.modules.discovery.schemas import SearchPlan, SearchQuery
from app.platform.cache.source_results import SourceResultCache, get_source_result_cache
from app.platform.http.circuit_breaker import CircuitBreaker


def _retry_after_seconds(value: str | None) -> int | None:
    if not value:
        return None
    if value.isdecimal():
        return int(value)
    try:
        date = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if date.tzinfo is None:
        date = date.replace(tzinfo=timezone.utc)
    return max(0, math.ceil((date - datetime.now(timezone.utc)).total_seconds()))


class SourceRegistry:
    def __init__(self, adapters, *, owner_id: str | None = None, cache: SourceResultCache | None = None):
        self.adapters = adapters
        self.owner_id = owner_id
        self.cache = cache
        self.breakers = {a.name: CircuitBreaker(failure_threshold=getattr(a, "breaker_failure_threshold", 3)) for a in adapters}
        self.health = []

    def _ordered_adapters(self, plan: SearchPlan):
        by_name = {a.name: a for a in self.adapters}
        explicit = [name for name in plan.filters.sources if name in by_name]
        base_names = explicit or [a.name for a in self.adapters]
        hinted = [name for name in plan.source_hints if name in base_names]
        ordered_names = list(dict.fromkeys([*hinted, *base_names]))
        return [by_name[name] for name in ordered_names]

    def _query_for(self, adapter, plan: SearchPlan, limit: int) -> SearchQuery:
        query_text = plan.topic
        if adapter.name in {"openalex", "crossref", "semantic_scholar", "core"} and plan.query_terms:
            query_text = " ".join(dict.fromkeys([plan.topic, *plan.query_terms]))
        return SearchQuery(
            query=query_text,
            filters=plan.filters,
            limit=limit,
            include_web=plan.include_web,
            domain_tags=plan.domain_tags,
            arxiv_categories=plan.arxiv_categories,
            query_terms=plan.query_terms,
        )

    async def fan_out(self, plan: SearchPlan, limit: int = 20):
        adapters = self._ordered_adapters(plan)
        settings = get_settings()
        # httpx timeouts apply per network operation, so a slow-trickling response can
        # run far past the intended budget. Enforce a hard per-source deadline here so
        # discovery latency stays predictable and degraded sources are reported instead
        # of blocking the whole fan-out (NFR-1.3, NFR-5.2).
        per_source = settings.source_timeout_s

        async def run(a):
            start = time.perf_counter()

            def health(status=HealthStatus.OK, error=None, retry_after_seconds=None, cached=False):
                return SourceHealth(
                    source=a.name, status=status, error=error,
                    latency_ms=round((time.perf_counter() - start) * 1000),
                    retry_after_seconds=retry_after_seconds, cached=cached,
                )

            br = self.breakers[a.name]
            if not br.allow():
                return health(HealthStatus.UNAVAILABLE, "circuit open"), []
            try:
                adapter_limit = min(limit, 8) if a.name == "web" else limit
                query = self._query_for(a, plan, adapter_limit)
                cache = self.cache
                if cache is None and self.owner_id is not None:
                    cache = get_source_result_cache()
                cache_key = None
                if cache is not None and self.owner_id is not None:
                    provider = getattr(getattr(a, "provider", None), "name", "")
                    identity = f"{type(a).__module__}.{type(a).__qualname__}:{a.name}:{provider}"
                    parameters = json.dumps(query.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
                    cache_key = (self.owner_id, identity, parameters)
                    stored = cache.get(cache_key)
                    if stored is not None:
                        return health(cached=True), stored
                async with asyncio.timeout(per_source):
                    rec = await a.search(query)
                br.record_success()
                if cache_key is not None:
                    cache.set(cache_key, rec)
                return health(), rec
            except TimeoutError:
                br.record_failure()
                return health(HealthStatus.DEGRADED, f"timed out after {per_source:g}s"), []
            except httpx.HTTPStatusError as exc:
                br.record_failure()
                code = exc.response.status_code
                if code == 429:
                    retry = _retry_after_seconds(exc.response.headers.get("retry-after"))
                    detail = f"rate limited by {a.name}; retry in {retry}s" if retry is not None else f"rate limited by {a.name}; retry shortly"
                    return health(HealthStatus.RATE_LIMITED, detail, retry), []
                return health(HealthStatus.DEGRADED, f"{a.name} returned HTTP {code}"), []
            except httpx.TimeoutException as exc:
                br.record_failure()
                return health(HealthStatus.DEGRADED, f"{a.name} network timed out ({type(exc).__name__})"), []
            except httpx.RequestError as exc:
                br.record_failure()
                return health(HealthStatus.DEGRADED, f"{a.name} request failed ({type(exc).__name__})"), []
            except ValueError as exc:
                br.record_failure()
                return health(HealthStatus.DEGRADED, str(exc)), []
            except Exception as exc:
                br.record_failure()
                message = str(exc) if isinstance(exc, RuntimeError) else f"{a.name} failed ({type(exc).__name__})"
                return health(HealthStatus.DEGRADED, message), []

        res = await asyncio.gather(*(run(a) for a in adapters), return_exceptions=False)
        self.health = [h for h, _ in res]
        return [r for _, rs in res for r in rs]
