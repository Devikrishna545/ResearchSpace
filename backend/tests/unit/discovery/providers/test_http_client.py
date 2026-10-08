import asyncio
import logging

import httpx
import pytest

from app.core.config import Settings
from app.core.logging import configure_logging
from app.shared.schemas.common import HealthStatus
from app.modules.discovery.schemas import SearchFilters, SearchPlan, SearchQuery
from app.platform.http import client as source_http
from app.modules.discovery.providers.arxiv import ArxivAdapter
from app.modules.discovery.providers.core import COREAdapter
from app.modules.discovery.providers.crossref import CrossrefAdapter
from app.modules.discovery.providers.openalex import OpenAlexAdapter
from app.modules.discovery.providers.pubmed import PubMedAdapter
from app.modules.discovery.providers.registry import SourceRegistry, _retry_after_seconds
from app.modules.discovery.providers.semantic_scholar import SemanticScholarAdapter
from app.modules.discovery.providers.web_providers.brave import BraveProvider
from app.modules.discovery.providers.web_providers.duckduckgo import DuckDuckGoProvider


async def test_all_adapters_reuse_one_pooled_client_with_isolated_credentials(monkeypatch):
    settings = Settings(
        source_contact_email="researcher@university.edu",
        core_api_key="core-test-key",
        semantic_scholar_api_key="scholar-test-key",
        brave_api_key="brave-test-key",
    )
    requests: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        path = request.url.path
        if request.url.host == "export.arxiv.org":
            return httpx.Response(200, text='<feed xmlns="http://www.w3.org/2005/Atom"></feed>')
        if request.url.host == "api.openalex.org":
            return httpx.Response(200, json={"results": []})
        if request.url.host == "api.crossref.org":
            return httpx.Response(200, json={"message": {"items": []}})
        if "esearch.fcgi" in path:
            return httpx.Response(200, json={"esearchresult": {"idlist": ["123"]}})
        if "esummary.fcgi" in path:
            return httpx.Response(200, json={"result": {"uids": ["123"], "123": {"title": "A real result"}}})
        if request.url.host == "api.semanticscholar.org":
            return httpx.Response(200, json={"data": []})
        if request.url.host == "api.core.ac.uk":
            return httpx.Response(200, json={"results": []})
        if request.url.host == "api.search.brave.com":
            return httpx.Response(200, json={"web": {"results": []}})
        if request.url.host == "lite.duckduckgo.com":
            return httpx.Response(200, text="<html></html>")
        raise AssertionError(f"Unexpected host: {request.url.host}")

    await source_http.close_shared_source_client()
    constructor = httpx.AsyncClient
    constructed = []

    def create_client(*args, **kwargs):
        client = constructor(*args, transport=httpx.MockTransport(answer), **kwargs)
        constructed.append(client)
        return client

    monkeypatch.setattr(source_http.httpx, "AsyncClient", create_client)
    adapters = (
        ArxivAdapter(settings), OpenAlexAdapter(settings, contact_email=settings.source_contact_email), CrossrefAdapter(settings),
        PubMedAdapter(settings), SemanticScholarAdapter(settings), COREAdapter(settings),
    )
    query = SearchQuery(query="research", limit=1)
    try:
        for _ in range(2):
            await asyncio.gather(*(adapter.search(query) for adapter in adapters))
            await asyncio.gather(BraveProvider(settings).search("research", 1), DuckDuckGoProvider(settings).search("research", 1))
        assert len(constructed) == 1
        assert all("mailto:researcher@university.edu" in request.headers["user-agent"] for request in requests)
        assert all(request.url.params.get("mailto") == "researcher@university.edu" for request in requests if request.url.host == "api.openalex.org")
        for request in requests:
            host = request.url.host
            assert request.headers.get("x-api-key") == ("scholar-test-key" if host == "api.semanticscholar.org" else None)
            assert request.headers.get("authorization") == ("Bearer core-test-key" if host == "api.core.ac.uk" else None)
            assert request.headers.get("x-subscription-token") == ("brave-test-key" if host == "api.search.brave.com" else None)
        assert not any(name in constructed[0].headers for name in ("x-api-key", "authorization", "x-subscription-token"))
    finally:
        await source_http.close_shared_source_client()
    assert constructed[0].is_closed


async def test_rate_limit_is_reported_as_rate_limit_not_timeout(monkeypatch):
    settings = Settings()

    def answer(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, request=request, headers={"Retry-After": "33"}, text="Too Many Requests")

    async with httpx.AsyncClient(transport=httpx.MockTransport(answer)) as client:
        monkeypatch.setattr(source_http, "get_source_client", lambda: client)
        registry = SourceRegistry([OpenAlexAdapter(settings)])
        plan = SearchPlan(topic="research", sub_queries=["research"], filters=SearchFilters())
        assert await registry.fan_out(plan, limit=1) == []
    health = registry.health[0]
    assert health.status == HealthStatus.RATE_LIMITED
    assert "rate limited by openalex; retry in 33s" == health.error
    assert health.retry_after_seconds == 33
    assert health.latency_ms is not None
    assert "timed out" not in health.error
    assert "https://" not in health.error


async def test_web_provider_rate_limit_is_not_silently_discarded(monkeypatch):
    settings = Settings()
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(429, request=request))) as client:
        monkeypatch.setattr(source_http, "get_source_client", lambda: client)

        class WebAdapter:
            name = "web"

            async def search(self, query):
                return await DuckDuckGoProvider(settings).search(query.query, query.limit)

        registry = SourceRegistry([WebAdapter()])
        await registry.fan_out(SearchPlan(topic="research", sub_queries=["research"], filters=SearchFilters()), limit=1)
    assert registry.health[0].status == HealthStatus.RATE_LIMITED


def test_contact_is_real_and_read_budget_is_below_hard_deadline():
    settings = Settings(source_user_agent="research-assistant/0.1 (mailto:local@example.invalid)")
    assert source_http.source_contact_email(settings) is None
    assert "mailto:" not in source_http.source_headers(settings)["User-Agent"]
    with pytest.raises(ValueError, match="genuine"):
        source_http.source_contact_email(Settings(source_contact_email="nobody@example.invalid"))
    for budget in (0.3, 8.0, 12.0):
        assert source_http.source_timeout(Settings(source_timeout_s=budget)).read < budget
    assert _retry_after_seconds("not a date") is None


def test_httpx_info_logging_cannot_expose_contact_query():
    logger = logging.getLogger("httpx")
    previous = logger.level
    try:
        configure_logging()
        assert not logger.isEnabledFor(logging.INFO)
    finally:
        logger.setLevel(previous)


async def test_openalex_mailto_is_explicit_and_not_inferred_from_user_agent(monkeypatch):
    requests = []

    def answer(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, request=request, json={"results": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(answer)) as client:
        monkeypatch.setattr(source_http, "get_source_client", lambda: client)
        query = SearchQuery(query="research", limit=1)
        await OpenAlexAdapter(Settings()).search(query)
        assert requests[-1].url.params.get("mailto") is None
        assert "mailto:" not in requests[-1].headers["user-agent"]
        await OpenAlexAdapter(Settings(source_user_agent="research-assistant/0.1 (mailto:researcher@university.edu)")).search(query)
        assert requests[-1].url.params.get("mailto") is None
        assert "mailto:" not in requests[-1].headers["user-agent"]
        await OpenAlexAdapter(Settings(unpaywall_email="fallback@university.edu")).search(query)
        assert requests[-1].url.params.get("mailto") is None
        await OpenAlexAdapter(Settings(), contact_email="fallback@university.edu").search(query)
        assert requests[-1].url.params.get("mailto") == "fallback@university.edu"
        await OpenAlexAdapter(Settings(source_contact_email="general@university.edu"), contact_email="openalex@university.edu").search(query)
        assert requests[-1].url.params.get("mailto") == "openalex@university.edu"
        assert "mailto:openalex@university.edu" in requests[-1].headers["user-agent"]
