from app.modules.papers.schemas.paper import Paper
from app.modules.papers.schemas.paper import RawPaperRecord
from app.modules.discovery.providers.deduplicator import Deduplicator
from app.modules.discovery.providers.normalizer import Normalizer
from app.shared.identifiers import arxiv_id_from_doi, canonical_arxiv_id
import pytest

def test_deduplicates_by_doi_and_merges_fields():
    papers=[Paper(title='A',doi='10.1/X',authors=['Ada Lovelace'],citation_count=1),Paper(title='A better',doi='10.1/x',authors=['Ada Lovelace','Grace Hopper'],abstract='abs',citation_count=10)]
    out=Deduplicator().merge(papers)
    assert len(out)==1
    assert out[0].abstract=='abs'
    assert out[0].citation_count==10

def test_deduplicates_fuzzy_title_author_year():
    papers=[Paper(title='Neural Retrieval for Science',authors=['Jane Doe'],year=2024),Paper(title='Neural retrieval for sciences',authors=['Jane Doe'],year=2024)]
    assert len(Deduplicator().merge(papers))==1


def test_merged_authors_prefer_full_names_over_unambiguous_initials():
    papers = [
        Paper(title="Study", doi="10.123/study", authors=["Vasudevan V", "Prabaharan J"], source="openalex"),
        Paper(title="Study", doi="10.123/study", authors=["Vinduja Vasudevan", "Janani Prabaharan"], source="crossref"),
    ]
    assert Deduplicator().merge(papers)[0].authors == ["Vinduja Vasudevan", "Janani Prabaharan"]


def test_authors_with_same_surname_and_initial_are_not_conflated():
    papers = [
        Paper(title="Study", doi="10.123/study", authors=["Alice Smith", "Andrew Smith"], source="openalex"),
        Paper(title="Study", doi="10.123/study", authors=["Smith A", "Amy Smith", "Bob Smith"], source="crossref"),
    ]
    assert Deduplicator().merge(papers)[0].authors == [
        "Alice Smith", "Andrew Smith", "Smith A", "Amy Smith", "Bob Smith",
    ]


def test_names_on_same_source_record_are_not_collapsed_by_initial():
    papers = [
        Paper(title="Study", doi="10.123/study", authors=["Alice Smith", "Smith A"], source="openalex"),
        Paper(title="Study", doi="10.123/study", authors=["Bob Jones"], source="crossref"),
    ]
    assert Deduplicator().merge(papers)[0].authors == ["Alice Smith", "Smith A", "Bob Jones"]


def test_deduplicator_merges_variants_and_stays_fast():
    """Regression: fuzzy dedup was O(n^2) with per-comparison normalization (~2.4s for 90 records)."""
    import time
    from app.modules.discovery.providers.deduplicator import Deduplicator
    from app.modules.papers.schemas.paper import Paper

    base = [Paper(title=f"Unique study number {i} about retrieval systems", authors=[f"Alpha Sur{i}"], year=2020 + (i % 5), source="a", raw_payload={}) for i in range(60)]
    dupes = [Paper(title=p.title, authors=p.authors, year=p.year, source="b", raw_payload={}) for p in base[:20]]
    start = time.perf_counter()
    merged = Deduplicator().merge(base + dupes)
    elapsed = time.perf_counter() - start
    assert len(merged) == 60
    assert elapsed < 0.5


def test_deduplicator_matches_on_identifiers_across_sources():
    from app.modules.discovery.providers.deduplicator import Deduplicator
    from app.modules.papers.schemas.paper import Paper

    a = Paper(title="A paper", doi="10.1000/XYZ", authors=["One Author"], year=2024, source="openalex", raw_payload={})
    b = Paper(title="Completely different rendering of the title", doi="https://doi.org/10.1000/xyz", authors=["Two Author"], year=2024, source="crossref", raw_payload={})
    c = Paper(title="Another", arxiv_id="arXiv:2401.00001", authors=["Three"], year=2024, source="arxiv", raw_payload={})
    d = Paper(title="Another again", arxiv_id="2401.00001", authors=["Four"], year=2024, source="s2", raw_payload={})
    merged = Deduplicator().merge([a, b, c, d])
    assert len(merged) == 2


def test_deduplicator_keeps_distinct_papers_with_similar_titles():
    from app.modules.discovery.providers.deduplicator import Deduplicator
    from app.modules.papers.schemas.paper import Paper

    a = Paper(title="Retrieval augmented generation for code", authors=["X Smith"], year=2023, source="a", raw_payload={})
    b = Paper(title="Retrieval augmented generation for music", authors=["Y Jones"], year=2024, source="b", raw_payload={})
    assert len(Deduplicator().merge([a, b])) == 2


@pytest.mark.parametrize(("doi", "identifier"), [
    ("10.48550/arXiv.2106.09685", "2106.09685"),
    ("https://doi.org/10.48550/ArXiV.2106.09685v2", "2106.09685"),
    ("doi:10.48550/arXiv.cs/0112017V2", "cs/0112017"),
    ("10.48550/ARXIV.HEP-TH/9901001v3", "hep-th/9901001"),
])
def test_datacite_doi_encodes_exact_arxiv_identifier(doi, identifier):
    assert arxiv_id_from_doi(doi) == identifier
    if "/" in identifier:
        assert canonical_arxiv_id(f"https://arxiv.org/abs/{identifier}v2") == identifier


@pytest.mark.parametrize("doi", [
    None, "10.1109/CVPR.2016.90", "10.48550/unrelated.2106.09685",
    "10.48550/arxiv.", "10.48550/arxiv.2106",
    "10.48550/arxiv.2113.09685", "10.48550/arxiv.cs/0113017",
    "10.48550/arxiv.2106.09685/other", "10.48550/arxiv.2106.09685vX",
])
def test_non_arxiv_or_malformed_doi_does_not_infer_identifier(doi):
    assert arxiv_id_from_doi(doi) is None


def test_datacite_doi_only_record_merges_with_same_arxiv_preprint():
    records = [
        RawPaperRecord(source="openalex", title="Different metadata rendering", doi="https://doi.org/10.48550/arXiv.2004.04906v3", authors=["Alice"]),
        RawPaperRecord(source="arxiv", title="Dense Passage Retrieval for Open-Domain Question Answering", arxiv_id="2004.04906", authors=["Bob"]),
    ]
    normalized = Normalizer().normalize(records)
    assert normalized[0].arxiv_id == "2004.04906"
    merged = Deduplicator().merge(normalized)
    assert len(merged) == 1
    assert merged[0].arxiv_id == "2004.04906"
    assert merged[0].doi == records[0].doi


def test_old_style_datacite_doi_merges_with_old_style_arxiv_url():
    records = [
        RawPaperRecord(source="openalex", title="Old archive rendering", doi="10.48550/arXiv.cs/0112017v2"),
        RawPaperRecord(source="arxiv", title="A different rendering", arxiv_id=canonical_arxiv_id("https://arxiv.org/abs/cs/0112017v3")),
    ]
    assert len(Deduplicator().merge(Normalizer().normalize(records))) == 1


def test_identifier_enrichment_never_merges_distinct_works():
    records = [
        RawPaperRecord(source="openalex", title="First preprint", doi="10.48550/arXiv.2004.04906"),
        RawPaperRecord(source="arxiv", title="Different paper entirely", arxiv_id="2004.04907"),
        RawPaperRecord(source="crossref", title="Published third work", doi="10.1109/CVPR.2016.90"),
    ]
    assert len(Deduplicator().merge(Normalizer().normalize(records))) == 3
    with pytest.raises(ValueError, match="conflicting arXiv identifiers"):
        Normalizer().normalize([
            RawPaperRecord(source="openalex", title="Mismatched metadata", doi="10.48550/arXiv.2004.04906", arxiv_id="2004.04907")
        ])
