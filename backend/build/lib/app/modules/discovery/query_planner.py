from app.modules.discovery.schemas import SearchFilters, SearchPlan
from app.modules.discovery.providers.taxonomy import DOMAIN_TAGS, parse_tags, plan_for_tags


class QueryPlanner:
    async def plan(self, topic: str, filters: SearchFilters | None = None, include_web: bool = False, domain_tags: list[str] | None = None, limit: int = 20) -> SearchPlan:
        clean_topic, tags, _unknown = parse_tags(topic)
        for tag in domain_tags or []:
            normalized = tag.lstrip("#").lower()
            if normalized in DOMAIN_TAGS and normalized not in tags:
                tags.append(normalized)
        tag_plan = plan_for_tags(tags)
        if not clean_topic and tags:
            clean_topic = " ".join(
                term
                for tag in tags
                for term in (DOMAIN_TAGS[tag].query_terms or (DOMAIN_TAGS[tag].label,))
            )
        clean_topic = clean_topic or topic.strip() or "research"
        parts = [clean_topic] + [p.strip() for p in clean_topic.split(" and ") if p.strip() and p.strip() != clean_topic]
        return SearchPlan(
            topic=clean_topic,
            sub_queries=list(dict.fromkeys(parts)),
            source_hints=list(tag_plan["source_priority"]),
            filters=filters or SearchFilters(),
            limit=limit,
            include_web=include_web,
            domain_tags=tags,
            arxiv_categories=list(tag_plan["arxiv_categories"]),
            query_terms=list(tag_plan["query_terms"]),
        )
