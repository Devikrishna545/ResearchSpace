import asyncio
from pathlib import Path

from app.modules.discovery.query_planner import QueryPlanner
from app.modules.discovery.ranking import RankingAgent
from app.core.config import Settings
from app.modules.papers.schemas.paper import Paper, RawPaperRecord
from app.modules.discovery.schemas import SearchFilters, SearchPlan, SearchQuery
from app.modules.discovery.providers.arxiv import ArxivAdapter
from app.modules.discovery.providers.pubmed import PubMedAdapter
from app.modules.discovery.providers.registry import SourceRegistry
from app.platform.http import client as source_http
from app.modules.discovery.providers.taxonomy import parse_tags
from app.modules.discovery.providers.web_providers import provider_from_settings
from app.modules.discovery.providers.web_providers.duckduckgo import parse_lite_results
from app.modules.discovery.api import source_adapters


def test_parse_tags_strips_known_tags_and_reports_unknowns():
    assert parse_tags("#medical sepsis") == ("sepsis", ["medical"], [])
    assert parse_tags("#ML #nlp x") == ("x", ["ml", "nlp"], [])
    assert parse_tags("C# generics") == ("C# generics", [], [])
    assert parse_tags("#banana retrieval") == ("retrieval", [], ["banana"])


def test_query_planner_strips_tags_and_sets_domain_plan():
    plan = asyncio.run(QueryPlanner().plan("#ML #nlp retrieval augmented generation"))
    assert plan.topic == "retrieval augmented generation"
    assert plan.domain_tags == ["ml", "nlp"]
    assert "arxiv" in plan.source_hints
    assert "cs.LG" in plan.arxiv_categories
    assert "cs.CL" in plan.arxiv_categories
    assert "machine learning" in plan.query_terms


def test_query_planner_tag_only_query_is_usable():
    plan = asyncio.run(QueryPlanner().plan("#medical"))
    assert plan.topic
    assert plan.domain_tags == ["medical"]
    assert plan.source_hints[0] == "pubmed"


class DummyAdapter:
    def __init__(self, name):
        self.name = name
        self.seen = []

    async def search(self, query):
        self.seen.append(query)
        return [RawPaperRecord(source=self.name, title=f"{self.name} paper")]


def test_source_registry_prioritizes_hints_and_keeps_explicit_sources():
    adapters = [DummyAdapter("arxiv"), DummyAdapter("pubmed"), DummyAdapter("openalex")]
    registry = SourceRegistry(adapters)
    plan = SearchPlan(topic="sepsis", sub_queries=["sepsis"], source_hints=["pubmed"], filters=SearchFilters())
    out = asyncio.run(registry.fan_out(plan, limit=3))
    assert [h.source for h in registry.health] == ["pubmed", "arxiv", "openalex"]
    assert [r.source for r in out] == ["pubmed", "arxiv", "openalex"]

    registry = SourceRegistry(adapters)
    plan.filters.sources = ["openalex", "arxiv"]
    out = asyncio.run(registry.fan_out(plan, limit=3))
    assert [h.source for h in registry.health] == ["openalex", "arxiv"]
    assert [r.source for r in out] == ["openalex", "arxiv"]


class FakeResponse:
    def __init__(self, *, text="", payload=None):
        self.text = text
        self._payload = payload or {}

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeArxivClient:
    params_seen = None

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def get(self, url, params=None, **kwargs):
        FakeArxivClient.params_seen = params
        return FakeResponse(text='<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>')


def test_arxiv_adapter_adds_category_fragment(monkeypatch):
    monkeypatch.setattr(source_http, "get_source_client", lambda: FakeArxivClient())
    asyncio.run(ArxivAdapter(Settings()).search(SearchQuery(query="rag", arxiv_categories=["cs.LG", "stat.ML"])))
    assert FakeArxivClient.params_seen["search_query"] == "all:rag AND (cat:cs.LG OR cat:stat.ML)"


class FakePubMedClient:
    def __init__(self, *args, **kwargs):
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def get(self, url, params=None, **kwargs):
        self.calls.append((url, params))
        if "esearch" in url:
            return FakeResponse(payload={"esearchresult": {"idlist": ["123", "456"]}})
        return FakeResponse(payload={"result": {"uids": ["123", "456"], "123": {"title": "Sepsis treatment in intensive care", "authors": [{"name": "Ada Smith"}], "fulljournalname": "New England Journal of Medicine", "pubdate": "2024 Jan", "articleids": [{"idtype": "doi", "value": "10.1/sepsis"}]}, "456": {"title": "Clinical decision support", "authors": [], "source": "Lancet", "pubdate": "2023", "articleids": []}}})


def test_pubmed_adapter_fetches_esummary_metadata(monkeypatch):
    monkeypatch.setattr(source_http, "get_source_client", lambda: FakePubMedClient())
    records = asyncio.run(PubMedAdapter(Settings()).search(SearchQuery(query="sepsis", limit=2)))
    assert [r.title for r in records] == ["Sepsis treatment in intensive care", "Clinical decision support"]
    assert records[0].authors == ["Ada Smith"]
    assert records[0].year == 2024
    assert records[0].venue == "New England Journal of Medicine"
    assert records[0].doi == "10.1/sepsis"


def test_ranking_agent_applies_domain_boost_and_explains_it():
    papers = [
        Paper(title="Sepsis treatment", source="pubmed", venue="Clinical Medicine"),
        Paper(title="Sepsis treatment", source="arxiv", raw_payload={"primary_category": "cs.LG", "categories": ["cs.LG"]}),
    ]
    ranked = asyncio.run(RankingAgent().rank(papers, "sepsis treatment", ["medical"]))
    assert ranked[0].paper.source == "pubmed"
    assert ranked[0].score > ranked[1].score
    assert "domain boost" in (ranked[0].rank_explanation or "")


def test_duckduckgo_lite_parser_decodes_redirect_links():
    html = """
    <html><body>
      <a class="result-link" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fpaper%3Fx%3D1">Example result</a>
      <td class="result-snippet">Useful web snippet.</td>
    </body></html>
    """
    results = parse_lite_results(html, 5)
    assert results[0].title == "Example result"
    assert results[0].url == "https://example.com/paper?x=1"
    assert results[0].snippet == "Useful web snippet."


def test_web_provider_selection_falls_back_without_key():
    settings = Settings(web_search_provider="brave", brave_api_key=None)
    assert provider_from_settings(settings).name == "duckduckgo"


def test_include_web_controls_adapter_registration():
    settings = Settings()
    assert "web" not in [adapter.name for adapter in source_adapters(settings, include_web=False)]
    names = [adapter.name for adapter in source_adapters(settings, include_web=True)]
    assert "web" in names


class CappedProvider:
    name = "fake"
    seen_limit = 0
    seen_query = ""

    async def search(self, query, limit):
        self.seen_limit = limit
        self.seen_query = query
        return []


def test_web_adapter_caps_results_and_adds_bias_terms():
    from app.modules.discovery.providers.web_search import WebSearchAdapter
    provider = CappedProvider()
    adapter = WebSearchAdapter(Settings(), provider=provider)
    asyncio.run(adapter.search(SearchQuery(query="rag", limit=20, query_terms=["machine learning"])))
    assert provider.seen_limit == 8
    assert "machine learning" in provider.seen_query


def test_backend_never_fetches_google_scholar():
    app_root = Path(__file__).resolve().parents[3] / "app"
    offenders = [path for path in app_root.rglob("*.py") if "scholar.google.com" in path.read_text(encoding="utf-8")]
    assert offenders == []
