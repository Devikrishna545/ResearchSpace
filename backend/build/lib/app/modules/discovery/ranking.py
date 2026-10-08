from datetime import datetime, timezone

from app.modules.discovery.schemas import RankedPaper
from app.modules.discovery.providers.taxonomy import DOMAIN_TAGS
from app.shared.text import tokenize

QUERY_STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in", "is",
    "it", "of", "on", "or", "that", "the", "to", "was", "were", "with",
})


class RankingAgent:
    def __init__(self, recency_weight: float = 0.0, remove_stopwords: bool = False):
        if not 0 <= recency_weight <= 0.06:
            raise ValueError("recency_weight must be between 0 and 0.06")
        self.recency_weight = recency_weight
        self.remove_stopwords = remove_stopwords

    async def rank(self, papers, topic: str, domain_tags: list[str] | None = None):
        q, ignored, kept_all = self._query_tokens(topic)
        active_tags = domain_tags or []
        ranked = []
        for p in papers:
            overlap = len(q & set(tokenize(" ".join([p.title, p.abstract or ""])))) / max(1, len(q))
            base = overlap + min(p.citation_count, 1000) / 10000 + (0.05 if p.pdf_url or p.oa_status else 0)
            recency, recency_reason = self._recency_component(p.year)
            boost, reasons = self._domain_boost(p, active_tags)
            explanation = "keyword+citation+OA heuristic"
            if self.recency_weight:
                explanation += f"; {recency_reason}"
            if ignored:
                explanation += f"; ignored {ignored} common query word{'s' if ignored != 1 else ''}"
            elif kept_all:
                explanation += "; all query words were common, so none were removed"
            if p.source == "web":
                base -= 0.15
                explanation += "; web result penalty to keep scholarly matches first"
            if boost:
                explanation += f"; domain boost ({', '.join(reasons)})"
            ranked.append(RankedPaper(paper=p, score=base + recency + boost, rank_explanation=explanation))
        return sorted(ranked, key=lambda r: r.score, reverse=True)

    def _query_tokens(self, topic: str) -> tuple[set[str], int, bool]:
        tokens = set(tokenize(topic))
        if not self.remove_stopwords:
            return tokens, 0, False
        content = tokens - QUERY_STOPWORDS
        if not content:
            return tokens, 0, bool(tokens)
        return content, len(tokens) - len(content), False

    def _recency_component(self, year: int | None) -> tuple[float, str]:
        if not self.recency_weight:
            return 0.0, "recency disabled"
        if year is None:
            return 0.0, "recency unavailable (year missing)"
        reference_year = getattr(self, "reference_year", datetime.now(timezone.utc).year)
        age = max(0, reference_year - year)
        # A small, capped signal breaks close lexical ties without outweighing relevance.
        value = self.recency_weight * max(0, 1 - age / 10)
        return value, f"recency +{value:.3f} ({age}y old)"

    def _domain_boost(self, paper, tags: list[str]) -> tuple[float, list[str]]:
        boost = 0.0
        reasons: list[str] = []
        haystack = " ".join([paper.source or "", paper.venue or "", paper.abstract or "", paper.title or ""]).lower()
        categories = set((paper.raw_payload or {}).get("categories") or [])
        primary = (paper.raw_payload or {}).get("primary_category")
        if primary:
            categories.add(primary)
        for tag in tags:
            item = DOMAIN_TAGS.get(tag)
            if not item:
                continue
            matched = False
            source_boost = 0.0
            if item.pubmed_relevant and paper.source == "pubmed":
                matched = True
                source_boost = 0.20
            elif item.pubmed_relevant and any(word in haystack for word in ("medical", "clinical", "health", "journal of medicine", "pubmed")):
                matched = True
                source_boost = 0.08
            if not matched and item.arxiv_categories:
                for category in item.arxiv_categories:
                    prefix = category[:-1] if category.endswith("*") else category
                    if any(c == category or (category.endswith("*") and c.startswith(prefix)) for c in categories):
                        matched = True
                        break
            if not matched and item.query_terms:
                matched = any(term.lower() in haystack for term in item.query_terms)
            if matched:
                boost += source_boost or 0.08
                reasons.append(f"#{tag}")
        return min(boost, 0.24), reasons
