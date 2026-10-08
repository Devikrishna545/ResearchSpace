from app.modules.discovery.query_planner import QueryPlanner
from app.modules.discovery.ranking import RankingAgent
from app.core.config import get_settings
from app.modules.discovery.schemas import RankedPaperList, SearchQuery
from app.modules.discovery.providers.deduplicator import Deduplicator
from app.modules.discovery.providers.normalizer import Normalizer


class DiscoveryService:
    def __init__(self, registry, planner=None, normalizer=None, deduplicator=None, ranking=None):
        self.registry = registry
        self.planner = planner or QueryPlanner()
        self.normalizer = normalizer or Normalizer()
        self.deduplicator = deduplicator or Deduplicator()
        self.ranking = ranking or RankingAgent(
            recency_weight=get_settings().ranking_recency_weight,
            remove_stopwords=get_settings().ranking_remove_stopwords,
        )

    async def discover(self, topic, filters=None):
        if isinstance(topic, SearchQuery):
            body = topic
            plan = await self.planner.plan(body.query, body.filters, include_web=body.include_web, domain_tags=body.domain_tags, limit=body.limit)
        else:
            plan = await self.planner.plan(topic, filters)
        raw = await self.registry.fan_out(plan, limit=plan.limit)
        papers = self.deduplicator.merge(self.normalizer.normalize(raw))
        ranked = await self.ranking.rank(papers, plan.topic, plan.domain_tags)
        web_results = []
        if plan.include_web:
            scholarly = [item for item in ranked if item.paper.source != "web"][:plan.limit]
            web_results = [item for item in ranked if item.paper.source == "web"][:8]
            ranked = scholarly
        else:
            ranked = [item for item in ranked if item.paper.source != "web"][:plan.limit]
        return RankedPaperList(results=ranked, web_results=web_results, source_health=self.registry.health)
