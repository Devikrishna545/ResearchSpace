from app.modules.papers.schemas.paper import Paper
from app.modules.discovery.schemas import RankedPaper, SearchPlan, SearchQuery
from app.modules.discovery.service import DiscoveryService


class Registry:
    health = []

    async def fan_out(self, plan, limit):
        return []


class Planner:
    async def plan(self, query, filters, include_web=False, domain_tags=None, limit=20):
        return SearchPlan(topic=query, sub_queries=[query], include_web=include_web, domain_tags=domain_tags or [], limit=limit)


class Normalizer:
    def normalize(self, raw):
        return raw


class Deduplicator:
    def merge(self, papers):
        return papers


class Ranking:
    async def rank(self, papers, topic, domain_tags):
        return [
            RankedPaper(paper=Paper(title="Web", source="web"), score=0.9),
            RankedPaper(paper=Paper(title="Paper", source="arxiv"), score=0.8),
        ]


async def test_search_response_partitions_web_from_scholarly():
    service = DiscoveryService(Registry(), planner=Planner(), normalizer=Normalizer(), deduplicator=Deduplicator(), ranking=Ranking())
    response = await service.discover(SearchQuery(query="rag", include_web=True))
    assert all(item.paper.source != "web" for item in response.results)
    assert all(item.paper.source == "web" for item in response.web_results)
