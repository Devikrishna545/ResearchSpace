"""Evaluate identifiable-paper ranking on frozen API candidates or a live fan-out.

From backend:
  python -m scripts.eval_ranking snapshot --report evaluations/reports/baseline.json
  python -m scripts.eval_ranking cached --compare-to evaluations/reports/baseline.json
  python -m scripts.eval_ranking live
"""

import argparse
import asyncio
import hashlib
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.engine import make_url

from app.modules.discovery.query_planner import QueryPlanner
from app.modules.discovery.ranking import RankingAgent
from app.modules.discovery.api import source_adapters
from app.core.config import get_settings
from app.modules.papers.schemas.paper import Paper, RawPaperRecord
from app.modules.discovery.schemas import SearchFilters, SearchPlan
from app.modules.discovery.providers.deduplicator import Deduplicator
from app.platform.http.client import close_shared_source_client
from app.modules.discovery.providers.normalizer import Normalizer
from app.modules.discovery.providers.registry import SourceRegistry
from app.shared.identifiers import canonical_arxiv_id, canonical_doi

BACKEND = Path(__file__).resolve().parents[1]
QUERIES = BACKEND / "evaluations" / "ranking_queries.json"
CACHE = BACKEND / "data" / "ranking-eval"
CATEGORIES = {"exact_title", "descriptive", "vocabulary_mismatch"}
RECORD_FIELDS = {
    "source", "title", "authors", "year", "venue", "abstract", "citation_count",
    "doi", "arxiv_id", "pmid", "openalex_id", "oa_status", "pdf_url",
}


def read_query_set(path: Path) -> tuple[list[dict], str]:
    content = path.read_bytes()
    document = json.loads(content)
    queries = document["queries"]
    if not 20 <= len(queries) <= 30 or {row["category"] for row in queries} != CATEGORIES:
        raise ValueError("Evaluation set needs 20–30 queries across all three categories")
    identifiers = set()
    for row in queries:
        name = row["id"]
        if not name or name in identifiers or not name.replace("-", "").isalnum():
            raise ValueError(f"Invalid or duplicate query ID: {name!r}")
        identifiers.add(name)
        if not row["query"].strip() or not set(row["target"]) <= {"arxiv_id", "doi"} or not row["target"]:
            raise ValueError(f"Query {name} needs text and at least one DOI or arXiv target")
        if not all(value.strip() for value in row["target"].values()):
            raise ValueError(f"Query {name} has an empty canonical identifier")
    return queries, hashlib.sha256(content).hexdigest()


def target_matches(paper: Paper | RawPaperRecord, target: dict) -> bool:
    return (
        ("arxiv_id" in target and canonical_arxiv_id(paper.arxiv_id) == canonical_arxiv_id(target["arxiv_id"]))
        or ("doi" in target and canonical_doi(paper.doi) == canonical_doi(target["doi"]))
    )


def compact_record(record: RawPaperRecord) -> dict:
    data = record.model_dump(include=RECORD_FIELDS, mode="json")
    payload = record.raw_payload or {}
    data["raw_payload"] = {key: payload[key] for key in ("categories", "primary_category") if key in payload}
    return data


def _database_contact(user_id: str) -> str:
    import sqlite3

    url = make_url(get_settings().database_url)
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        raise RuntimeError("Consented evaluation requires a local SQLite database")
    database = Path(url.database)
    if not database.is_absolute():
        database = BACKEND / database
    with sqlite3.connect("file:" + database.resolve().as_posix() + "?mode=ro", uri=True) as connection:
        record = connection.execute(
            "SELECT contact_email FROM openalex_consents WHERE user_id=? AND state='granted'",
            (user_id,),
        ).fetchone()
    if not record or not record[0]:
        raise ValueError("Selected member has not granted OpenAlex identification consent")
    return record[0]


async def collect(row: dict, contact: str | None, limit: int) -> dict:
    settings = get_settings()
    plan = await QueryPlanner().plan(row["query"], SearchFilters(), limit=limit)
    registry = SourceRegistry(source_adapters(settings, openalex_contact=contact))
    records = await registry.fan_out(plan, limit=limit)
    if not records and all(health.status != "ok" for health in registry.health):
        raise RuntimeError(f"All discovery sources failed for {row['id']}; inspect source health before snapshotting")
    return {
        "id": row["id"],
        "category": row["category"],
        "query": row["query"],
        "target": row["target"],
        "plan": plan.model_dump(mode="json"),
        "candidates": [compact_record(record) for record in records],
        "source_health": [health.model_dump(mode="json") for health in registry.health],
    }


def _fixture_file(cache: Path, query_id: str) -> Path:
    return cache / f"{query_id}.json"


async def snapshot(queries: list[dict], digest: str, cache: Path, contact: str | None, limit: int, delay: float) -> list[dict]:
    cache.mkdir(parents=True, exist_ok=True)
    manifest_path = cache / "manifest.json"
    if manifest_path.exists():
        raise FileExistsError(f"Snapshot already exists at {cache}; use cached mode or choose a different directory")
    fixtures = []
    manifest_files = {}
    for row in queries:
        path = _fixture_file(cache, row["id"])
        if path.exists():
            fixture = json.loads(path.read_text(encoding="utf-8"))
            if (fixture["dataset_sha256"], fixture["identified_openalex"]) != (digest, bool(contact)):
                raise ValueError(f"Partial snapshot {path} belongs to a different query set or consent mode")
        else:
            fixture = await collect(row, contact, limit)
            fixture["dataset_sha256"] = digest
            fixture["identified_openalex"] = bool(contact)
            path.write_text(json.dumps(fixture, indent=2, ensure_ascii=False), encoding="utf-8")
            health = [(h["source"], h["status"]) for h in fixture["source_health"]]
            print(f"SNAPSHOT {row['id']} candidates={len(fixture['candidates'])} health={health}", flush=True)
            if row != queries[-1]:
                await asyncio.sleep(delay)
        fixtures.append(fixture)
        manifest_files[row["id"]] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {
        "version": 1,
        "dataset_sha256": digest,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "reference_year": datetime.now(timezone.utc).year,
        "identified_openalex": bool(contact),
        "per_source_limit": limit,
        "files": manifest_files,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return fixtures


def cached(queries: list[dict], digest: str, cache: Path) -> tuple[list[dict], dict]:
    path = cache / "manifest.json"
    if not path.exists():
        raise FileNotFoundError(f"No cached candidate snapshot at {cache}; run snapshot mode first")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest["dataset_sha256"] != digest or manifest["version"] != 1:
        raise ValueError("Cached candidates do not match this query set")
    fixtures = []
    for row in queries:
        fixture_path = _fixture_file(cache, row["id"])
        actual = hashlib.sha256(fixture_path.read_bytes()).hexdigest()
        if actual != manifest["files"][row["id"]]:
            raise ValueError(f"Cached candidates changed: {fixture_path}")
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        if fixture["id"] != row["id"] or fixture["target"] != row["target"]:
            raise ValueError(f"Wrong target in cached fixture: {fixture_path}")
        fixtures.append(fixture)
    return fixtures, manifest


async def evaluate(fixtures: list[dict], digest: str, mode: str, reference_year: int, recency_weight: float = 0.0, remove_stopwords: bool = False) -> dict:
    details = []
    ranker = RankingAgent(recency_weight=recency_weight, remove_stopwords=remove_stopwords)
    ranker.reference_year = reference_year
    for item in fixtures:
        records = [RawPaperRecord.model_validate(record) for record in item["candidates"]]
        raw_target = any(target_matches(record, item["target"]) for record in records)
        papers = Deduplicator().merge(Normalizer().normalize(records))
        plan = SearchPlan.model_validate(item["plan"])
        ranked = await ranker.rank(papers, plan.topic, plan.domain_tags)
        hits = [position for position, result in enumerate(ranked, start=1) if target_matches(result.paper, item["target"])]
        if raw_target and not hits:
            raise RuntimeError(f"Target identifier was lost while merging: {item['id']}")
        details.append({
            "id": item["id"],
            "category": item["category"],
            "query": item["query"],
            "target": item["target"],
            "candidates": len(papers),
            "target_present": bool(hits),
            "rank": min(hits) if hits else None,
            "target_match_count": len(hits),
            "source_health": item["source_health"],
        })
    return {
        "dataset_sha256": digest,
        "mode": mode,
        "reference_year": reference_year,
        "scoring_options": {"recency_weight": recency_weight, "remove_stopwords": remove_stopwords},
        "overall": metrics(details),
        "categories": {category: metrics([row for row in details if row["category"] == category]) for category in sorted(CATEGORIES)},
        "queries": details,
    }


def metrics(rows: list[dict]) -> dict:
    ranks = [row["rank"] for row in rows if row["rank"] is not None]
    count = len(rows)
    present = len(ranks)
    return {
        "queries": count,
        "target_absent": count - len(ranks),
        "target_present": len(ranks),
        "ranking_failures_at_10": sum(rank > 10 for rank in ranks),
        "ranking_failures_at_20": sum(rank > 20 for rank in ranks),
        "recall_at_10": round(sum(rank <= 10 for rank in ranks) / count, 4) if count else 0,
        "recall_at_20": round(sum(rank <= 20 for rank in ranks) / count, 4) if count else 0,
        "mrr": round(sum(1 / rank for rank in ranks) / count, 4) if count else 0,
        "recall_at_10_present": round(sum(rank <= 10 for rank in ranks) / present, 4) if present else None,
        "recall_at_20_present": round(sum(rank <= 20 for rank in ranks) / present, 4) if present else None,
        "mrr_present": round(sum(1 / rank for rank in ranks) / present, 4) if present else None,
        "median_rank_present": round(statistics.median(ranks), 3) if ranks else None,
        "mean_rank_present": round(statistics.mean(ranks), 3) if ranks else None,
    }


def display(report: dict, previous: dict | None = None) -> None:
    if previous and (previous["dataset_sha256"], previous["mode"]) != (report["dataset_sha256"], "cached"):
        raise ValueError("A rank comparison requires the same frozen dataset and a cached baseline")
    for category, result in [("overall", report["overall"]), *report["categories"].items()]:
        print(
            f"{category}: n={result['queries']} absent={result['target_absent']} "
            f"ranking_misses@10={result['ranking_failures_at_10']} "
            f"recall@10={result['recall_at_10']:.3f} recall@20={result['recall_at_20']:.3f} "
            f"MRR={result['mrr']:.3f} median_rank_present={result['median_rank_present']} "
            f"mean_rank_present={result['mean_rank_present']} "
            f"present_only_recall@10={result['recall_at_10_present']} "
            f"present_only_recall@20={result['recall_at_20_present']} "
            f"present_only_MRR={result['mrr_present']}"
        )
    prior = {row["id"]: row for row in previous["queries"]} if previous else {}
    print("query_id | category | candidates | target_present | rank_before | rank_after | delta")
    for row in report["queries"]:
        before = prior[row["id"]]["rank"] if previous else None
        after = row["rank"]
        delta = before - after if before is not None and after is not None else None
        print(
            f"{row['id']} | {row['category']} | {row['candidates']} | {row['target_present']} | "
            f"{before if before is not None else '-'} | {after if after is not None else 'ABSENT'} | "
            f"{delta if delta is not None else '-'}"
        )


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["snapshot", "cached", "live"])
    parser.add_argument("--queries", type=Path, default=QUERIES)
    parser.add_argument("--cache", type=Path, default=CACHE)
    parser.add_argument("--per-source-limit", type=int, default=20)
    parser.add_argument("--delay", type=float, default=3.2, help="Seconds between fresh API fan-outs")
    parser.add_argument("--consented-user", help="Optional user ID; reads only that member's granted contact, never stores or displays it")
    parser.add_argument("--report", type=Path, help="Write metadata-only metrics; never stores contact or candidate abstracts")
    parser.add_argument("--compare-to", type=Path, help="Compare only on identical cached candidates")
    parser.add_argument("--recency-weight", type=float, default=0.0, help="Opt-in recency signal; default 0 after landmark-only audit")
    parser.add_argument("--remove-stopwords", action="store_true", help="Opt in to audited common-query-word filtering")
    args = parser.parse_args()
    if args.per_source_limit < 20 or args.delay < 0:
        parser.error("Use at least 20 candidates per source and a non-negative API pause")
    if args.mode == "cached" and args.consented_user:
        parser.error("Cached mode reads only fixtures and cannot access member settings")
    if args.compare_to and args.mode != "cached":
        parser.error("Rank deltas require cached mode to keep candidate sets identical")
    queries, digest = read_query_set(args.queries)
    contact = _database_contact(args.consented_user) if args.consented_user else None
    try:
        if args.mode == "cached":
            fixtures, manifest = cached(queries, digest, args.cache)
            reference_year = manifest["reference_year"]
        elif args.mode == "snapshot":
            fixtures = await snapshot(queries, digest, args.cache, contact, args.per_source_limit, args.delay)
            reference_year = json.loads((args.cache / "manifest.json").read_text(encoding="utf-8"))["reference_year"]
        else:
            fixtures = []
            for row in queries:
                fixture = await collect(row, contact, args.per_source_limit)
                fixtures.append(fixture)
                health = [(h["source"], h["status"]) for h in fixture["source_health"]]
                print(f"LIVE {row['id']} candidates={len(fixture['candidates'])} health={health}", flush=True)
                if row != queries[-1]:
                    await asyncio.sleep(args.delay)
            reference_year = datetime.now(timezone.utc).year
    finally:
        await close_shared_source_client()
    report = await evaluate(
        fixtures, digest, "cached" if args.mode != "live" else "live",
        reference_year, recency_weight=args.recency_weight, remove_stopwords=args.remove_stopwords,
    )
    baseline = json.loads(args.compare_to.read_text(encoding="utf-8")) if args.compare_to else None
    display(report, baseline)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Report saved to {args.report}")


if __name__ == "__main__":
    asyncio.run(main())
