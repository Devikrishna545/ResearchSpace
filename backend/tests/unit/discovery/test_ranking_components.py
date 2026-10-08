import pytest

from app.modules.discovery.ranking import RankingAgent
from app.modules.papers.schemas.paper import Paper


async def test_recency_prefers_recent_work_on_equal_relevance():
    ranker = RankingAgent(recency_weight=0.06)
    ranker.reference_year = 2026
    old = Paper(title="Paper", year=2016)
    recent = Paper(title="Paper", year=2025)
    unknown = Paper(title="Paper")
    results = await ranker.rank([old, unknown, recent], "paper")
    assert [result.paper.year for result in results] == [2025, 2016, None]
    assert results[0].score - results[1].score == pytest.approx(0.054)
    assert "recency +0.054 (1y old)" in results[0].rank_explanation
    assert "recency +0.000 (10y old)" in results[1].rank_explanation
    assert "recency unavailable (year missing)" in results[2].rank_explanation
    assert ranker._recency_component(2028)[0] == pytest.approx(0.06)


async def test_recency_is_disabled_by_default_and_preserves_lexical_rank():
    ranker = RankingAgent()
    ranker.reference_year = 2026
    old = Paper(title="Same topic", year=2016)
    recent = Paper(title="Same topic", year=2025)
    ranked = await ranker.rank([old, recent], "same topic")
    assert [item.paper.year for item in ranked] == [2016, 2025]
    assert ranked[0].score == ranked[1].score
    assert all(item.rank_explanation == "keyword+citation+OA heuristic" for item in ranked)


async def test_missing_abstract_has_no_zero_field_penalty():
    ranker = RankingAgent()
    title_only = Paper(title="Transformer sequence model", abstract=None)
    irrelevant_abstract = Paper(title="Transformer sequence model", abstract="Unrelated biology")
    informative_abstract = Paper(title="Transformer sequence model", abstract="Transduction evidence")
    results = await ranker.rank([title_only, irrelevant_abstract], "transformer sequence model")
    assert [item.paper for item in results] == [title_only, irrelevant_abstract]
    assert results[0].score == results[1].score
    assert "keyword+citation+OA heuristic" in results[0].rank_explanation
    with_evidence = await ranker.rank([title_only, informative_abstract], "transformer transduction")
    assert with_evidence[0].paper is informative_abstract


async def test_common_query_words_do_not_dilute_content_overlap():
    paper = Paper(title="Patient records")
    ranker = RankingAgent(remove_stopwords=True)
    filtered = (await ranker.rank([paper], "the use of patient records"))[0]
    original = (await RankingAgent().rank([paper], "the use of patient records"))[0]
    assert filtered.score == pytest.approx(2 / 3)
    assert original.score == pytest.approx(2 / 5)
    assert "ignored 2 common query words" in filtered.rank_explanation
    assert "ignored" not in original.rank_explanation


async def test_all_common_words_keep_a_nonempty_query():
    result = (await RankingAgent(remove_stopwords=True).rank([Paper(title="the patient")], "the and of"))[0]
    assert result.score == pytest.approx(1 / 3)
    assert "all query words were common, so none were removed" in result.rank_explanation
