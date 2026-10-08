import hashlib
import json
from collections import Counter

from app.modules.discovery.schemas import SearchFilters, SearchPlan
from scripts.eval_ranking import QUERIES, cached, evaluate, metrics, read_query_set, target_matches
from scripts.eval_abstract_availability import audit
from app.modules.papers.schemas.paper import Paper


def test_query_set_has_known_identifier_targets_and_all_categories():
    queries, digest = read_query_set(QUERIES)
    assert len(queries) == 24 and len(digest) == 64
    assert Counter(query["category"] for query in queries) == {
        "exact_title": 8, "descriptive": 8, "vocabulary_mismatch": 8,
    }
    assert len({query["id"] for query in queries}) == 24
    target = {"arxiv_id": "2004.04906"}
    assert target_matches(Paper(title="Different wording", arxiv_id="2004.04906v3"), target)
    assert not target_matches(Paper(title="Dense Passage Retrieval for Open-Domain Question Answering"), target)
    aliases = {"arxiv_id": "1512.03385", "doi": "10.1109/CVPR.2016.90"}
    assert target_matches(Paper(title="Unrelated title", doi="https://doi.org/10.1109/CVPR.2016.90"), aliases)


def test_metrics_separate_missing_candidates_from_ranking_failures():
    summary = metrics([{"rank": 1}, {"rank": 15}, {"rank": None}])
    assert summary["queries"] == 3
    assert summary["target_absent"] == 1
    assert summary["ranking_failures_at_10"] == 1
    assert summary["ranking_failures_at_20"] == 0
    assert summary["recall_at_10"] == 0.3333
    assert summary["recall_at_20"] == 0.6667
    assert summary["mrr"] == 0.3556
    assert summary["recall_at_10_present"] == 0.5
    assert summary["recall_at_20_present"] == 1.0
    assert summary["mrr_present"] == 0.5333
    assert summary["median_rank_present"] == 8
    assert summary["mean_rank_present"] == 8


async def test_cached_mode_is_offline_stable_and_rejects_changed_candidates(tmp_path):
    queries, digest = read_query_set(QUERIES)
    files = {}
    for index, query in enumerate(queries):
        plan = SearchPlan(topic=query["query"], sub_queries=[query["query"]], filters=SearchFilters())
        title_only = {"source": "arxiv", "title": query["query"], "abstract": None}
        target = {"source": "arxiv", "title": "Identifiable paper", **query["target"]}
        fixture = {
            **query,
            "plan": plan.model_dump(mode="json"),
            "candidates": [title_only, target] if index == 0 else [title_only],
            "source_health": [],
        }
        path = tmp_path / f"{query['id']}.json"
        path.write_text(json.dumps(fixture), encoding="utf-8")
        files[query["id"]] = hashlib.sha256(path.read_bytes()).hexdigest()
    (tmp_path / "manifest.json").write_text(json.dumps({
        "version": 1, "dataset_sha256": digest, "reference_year": 2026,
        "files": files,
    }), encoding="utf-8")
    fixtures, manifest = cached(queries, digest, tmp_path)
    first = await evaluate(fixtures, digest, "cached", manifest["reference_year"])
    second = await evaluate(fixtures, digest, "cached", manifest["reference_year"])
    assert first == second
    assert first["overall"]["target_present"] == 1
    assert first["overall"]["target_absent"] == 23
    assert first["queries"][0]["rank"] is not None
    assert first["queries"][1]["rank"] is None
    (tmp_path / f"{queries[0]['id']}.json").write_text("{}", encoding="utf-8")
    import pytest
    with pytest.raises(ValueError, match="changed"):
        cached(queries, digest, tmp_path)


async def test_abstract_audit_counts_present_title_only_target_without_inventing_harm():
    plan = SearchPlan(topic="transformer", sub_queries=["transformer"], filters=SearchFilters())
    fixture = {
        "id": "title-only",
        "category": "exact_title",
        "target": {"arxiv_id": "1706.03762"},
        "plan": plan.model_dump(mode="json"),
        "source_health": [],
        "candidates": [
            {"source": "arxiv", "title": "Transformer", "arxiv_id": "1706.03762", "abstract": None},
            {"source": "other", "title": "Unrelated", "abstract": "biology"},
        ],
    }
    report = await audit([fixture], "test-dataset")
    assert report["candidate_appearances"] == 2
    assert report["missing_abstract_appearances"] == 1
    assert report["present_target_appearances"] == 1
    assert report["present_targets_without_abstract"] == [{"query_id": "title-only", "rank": 1}]
    assert report["abstractless_present_targets_outranked"] == 0


async def test_verified_preprint_and_published_doi_aliases_use_best_rank():
    plan = SearchPlan(topic="residual learning", sub_queries=["residual learning"], filters=SearchFilters())
    fixture = {
        "id": "verified-aliases",
        "category": "exact_title",
        "query": "residual learning",
        "target": {"arxiv_id": "1512.03385", "doi": "10.1109/CVPR.2016.90"},
        "plan": plan.model_dump(mode="json"),
        "source_health": [],
        "candidates": [
            {"source": "crossref", "title": "Deep Residual Learning", "doi": "10.1109/CVPR.2016.90", "year": 2016},
            {"source": "openalex", "title": "Preprint", "doi": "10.48550/arxiv.1512.03385", "year": 2015},
        ],
    }
    result = await evaluate([fixture], "alias-test", "cached", 2026)
    assert result["queries"][0]["target_present"]
    assert result["queries"][0]["target_match_count"] == 2
    assert result["queries"][0]["rank"] == 1
