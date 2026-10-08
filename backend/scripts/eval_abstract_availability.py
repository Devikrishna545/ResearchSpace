"""Audit the frozen candidate cache for missing abstracts without changing ranking."""

import argparse
import asyncio
import json
import statistics
from pathlib import Path

from app.modules.discovery.ranking import RankingAgent
from app.modules.papers.schemas.paper import RawPaperRecord
from app.modules.discovery.schemas import SearchPlan
from app.modules.discovery.providers.deduplicator import Deduplicator
from app.modules.discovery.providers.normalizer import Normalizer
from app.shared.identifiers import canonical_arxiv_id, canonical_doi
from app.shared.text import tokenize
from scripts.eval_ranking import CACHE, QUERIES, cached, read_query_set, target_matches


def summarize_group(values: list[dict]) -> dict:
    return {
        "appearances": len(values),
        "mean_score": round(statistics.mean(v["score"] for v in values), 4) if values else None,
        "median_score": round(statistics.median(v["score"] for v in values), 4) if values else None,
        "mean_rank": round(statistics.mean(v["rank"] for v in values), 3) if values else None,
        "median_rank": round(statistics.median(v["rank"] for v in values), 3) if values else None,
        "ranked_at_10": sum(v["rank"] <= 10 for v in values),
        "ranked_at_20": sum(v["rank"] <= 20 for v in values),
    }


async def audit(fixtures: list[dict], dataset_sha256: str) -> dict:
    groups: dict[str, list[dict]] = {"missing_abstract": [], "with_abstract": []}
    per_query = []
    unique: set[str] = set()
    target_count = 0
    target_missing = []
    for fixture in fixtures:
        records = [RawPaperRecord.model_validate(item) for item in fixture["candidates"]]
        papers = Deduplicator().merge(Normalizer().normalize(records))
        plan = SearchPlan.model_validate(fixture["plan"])
        ranked = await RankingAgent(remove_stopwords=False).rank(papers, plan.topic, plan.domain_tags)
        without = 0
        for rank, item in enumerate(ranked, start=1):
            paper = item.paper
            missing = not tokenize(paper.abstract or "")
            if missing:
                without += 1
            groups["missing_abstract" if missing else "with_abstract"].append({"score": item.score, "rank": rank})
            identifier = canonical_arxiv_id(paper.arxiv_id) or canonical_doi(paper.doi)
            unique.add(identifier or f"{paper.source}:{paper.title.lower()}")
            if target_matches(paper, fixture["target"]):
                target_count += 1
                if missing:
                    target_missing.append({"query_id": fixture["id"], "rank": rank})
        per_query.append({
            "query_id": fixture["id"],
            "category": fixture["category"],
            "candidates": len(ranked),
            "missing_abstract": without,
        })
    count = sum(len(group) for group in groups.values())
    return {
        "dataset_sha256": dataset_sha256,
        "candidate_appearances": count,
        "approx_distinct_identifiers_or_source_titles": len(unique),
        "missing_abstract_appearances": len(groups["missing_abstract"]),
        "missing_abstract_share": round(len(groups["missing_abstract"]) / count, 4) if count else 0,
        "groups": {name: summarize_group(values) for name, values in groups.items()},
        "present_target_appearances": target_count,
        "present_targets_without_abstract": target_missing,
        "abstractless_present_targets_outranked": sum(item["rank"] > 1 for item in target_missing),
        "per_query": per_query,
        "interpretation": (
            "No abstract-less present target was outranked. Group-wide score/rank differences "
            "are observational and confounded by query relevance, source and citations; this "
            "cache does not demonstrate target harm requiring a compensating ranking boost."
            if all(item["rank"] == 1 for item in target_missing) else
            "Some abstract-less targets were outranked; independent relevance judgments are "
            "required before attributing the difference to missing metadata."
        ),
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=CACHE)
    parser.add_argument("--report", type=Path, default=QUERIES.parent / "reports" / "abstract-availability-audit.json")
    args = parser.parse_args()
    queries, digest = read_query_set(QUERIES)
    fixtures, _manifest = cached(queries, digest, args.cache)
    report = await audit(fixtures, digest)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("ABSTRACT_AVAILABILITY", {key: value for key, value in report.items() if key not in {"groups", "per_query"}})
    print("GROUPS", report["groups"])
    print("Report saved to", args.report)


if __name__ == "__main__":
    asyncio.run(main())
