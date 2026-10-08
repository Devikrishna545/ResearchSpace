import ast
import json
import sqlite3
from pathlib import Path

import numpy as np
import pytest

from chat_chunking.benchmark import safe_run
from chat_chunking.chunking import (STRATEGIES, chunk_documents, encoding,
                                    recursive_spans, token_spans, tokens)
from chat_chunking.corpus import Block, Document, ROOT, load_corpus, merge_saved_chunks, snapshot, table_rows
from chat_chunking.evaluation import (answer_metrics, bind_cases, covered, passes,
                                      relevance_metrics, review_metrics, summary, threshold_sweep)
from chat_chunking.retrieval import retrieve, serialized


def document():
    doc = Document("paper-1", "Example Research", "test", [
        Block("Introduction. " + "A useful scientific observation. " * 150, 1, "Introduction"),
        Block("Methods. " + "Methods use different measurements. " * 180, 2, "Methods", "2.1 Setup"),
        Block("Table 1: Samples | Accuracy\nA | 95\nB | 70", 2, "Results", kind="table"),
        Block("Figure 1: Accuracy rises with sample size.", 2, "Results", kind="figure"),
    ])
    doc.finalize()
    return doc


def embed(texts):
    result = np.asarray([[1.0, 0.2 if "Methods" in t else 1.0] for t in texts])
    return result / np.linalg.norm(result, axis=1, keepdims=True)


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_chunking_preserves_provenance_and_bounds(strategy):
    doc = document()
    result = chunk_documents([doc], strategy, embed)
    limit = 650 if strategy == "baseline" else 800
    assert result.children
    for chunk in [*result.children, *result.parents.values()]:
        assert chunk.text == doc.text[chunk.start:chunk.end]
        assert 0 < tokens(chunk.text) <= limit
        assert chunk.doc_id == doc.doc_id
    for block in doc.blocks:
        assert covered({"doc_id": doc.doc_id, "start": block.start, "end": block.end},
                       result.children)
    if strategy.startswith("hierarchical"):
        assert result.parents
        for child in result.children:
            if child.parent_id:
                parent = result.parents[child.parent_id]
                assert parent.start <= child.start < child.end <= parent.end
    if strategy == "hierarchical_semantic_structured":
        assert any(c.kind == "table" and c.parent_id is None for c in result.children)
        assert any(c.kind == "figure" and c.parent_id is None for c in result.children)


def test_baseline_exact_size_and_overlap():
    text = " ".join(f"sample{i}" for i in range(2000))
    spans = token_spans(text, 0, len(text), 650, 81)
    assert len(spans) > 2
    for left, right in spans[:-1]:
        assert 500 <= tokens(text[left:right]) <= 800
        assert tokens(text[left:right]) == 650
    for first, second in zip(spans, spans[1:]):
        overlap = tokens(text[second[0]:first[1]])
        assert 0.10 <= overlap / 650 <= 0.15
    assert spans[0][0] == 0 and spans[-1][1] == len(text)


def test_recursive_unicode_and_long_paragraphs_preserve_text():
    text = "αβλ 東京 naïve research. " * 300
    spans = recursive_spans(text, 0, len(text), 80)
    assert "".join(text[a:b] for a, b in spans) == text
    assert all(tokens(text[a:b]) <= 80 for a, b in spans)


def test_structured_chunks_do_not_cross_known_section_boundaries():
    doc = document()
    chunks = chunk_documents([doc], "research_aware")
    for chunk in chunks.children:
        sections = {b.section for b in doc.blocks if b.end > chunk.start and b.start < chunk.end}
        assert len(sections) == 1


def test_hierarchical_retrieval_deduplicates_parents_and_obeys_serialized_budget():
    doc = document()
    chunks = chunk_documents([doc], "hierarchical_recursive")
    vectors = embed([c.text for c in chunks.children])
    contexts, _ = retrieve("scientific observation", embed(["query"])[0], chunks, vectors, budget=1000)
    assert contexts
    assert len({c.chunk_id for c in contexts}) == len(contexts)
    assert tokens(serialized(contexts)) <= 1000
    assert all(c.chunk_id in chunks.parents for c in contexts)


def test_gold_labels_bind_to_source_not_chunk_ids():
    doc = document()
    case = bind_cases([doc], {"cases": [{
        "id": "q", "evidence": [{"title": "Example Research", "pattern": "Table 1: Samples"}],
        "concepts": ["95"], "split": "held_out",
    }]})[0]
    chunkset = chunk_documents([doc], "baseline")
    assert relevance_metrics(case, chunkset.children)["evidence_recall"] == 1
    with pytest.raises(ValueError, match="not found"):
        bind_cases([doc], {"cases": [{"id": "bad", "evidence": [{"title": "Example", "pattern": "imaginary evidence"}]}]})


def test_high_scores_cannot_override_missing_quote_provenance_or_wrong_ids():
    doc = document()
    chunk = chunk_documents([doc], "research_aware").children[0]
    claims = [{"claim_id": "c1", "text": "An observation", "cited_chunk_ids": [chunk.chunk_id]}]
    result = review_metrics(claims, [chunk], {"overall_score": 0.99, "verdict": "APPROVED",
        "claims": [{"claim_id": "c1", "status": "SUPPORTED", "evidence_quote": "fabricated quotation", "issue": ""}]},
        {"c1": 0.99})
    assert result["quote_provenance_rate"] == 0
    assert not passes({**result, "claim_count": 1, "citation_validity": 1}, 0.9, 0.65)
    with pytest.raises(ValueError, match="exactly once"):
        review_metrics(claims, [chunk], {"overall_score": 1, "claims": []}, {})


def test_threshold_equalities_and_calibration_do_not_use_held_out_labels():
    valid = {"split": "calibration", "claim_count": 1, "review_verdict": "APPROVED",
             "review_score": 0.9, "supported_claim_rate": 1, "citation_validity": 1,
             "quote_provenance_rate": 1, "min_citation_similarity": 0.65,
             "reference_supported_answer": True}
    assert passes(valid, 0.9, 0.65)
    assert not passes(valid, 0.9, 0.65001)
    assert not passes({**valid, "supported_claim_rate": 0.5}, 0.8, 0.5)
    rows = [dict(valid) for _ in range(4)]
    _, before = threshold_sweep(rows)
    _, after = threshold_sweep(rows + [{**valid, "split": "held_out", "reference_supported_answer": False}] * 100)
    assert before == after


def test_abstention_and_errors_are_not_removed_from_accuracy_denominators():
    case = {"concepts": ["real fact"], "gold_groups": [], "unanswerable": True}
    assert answer_metrics(case, [], [])["full_rubric_match"]
    aggregate = summary([
        {"unanswerable": False, "answer_rubric_coverage": 1, "full_rubric_match": True},
        {"unanswerable": False, "answer_rubric_coverage": 0, "error": "timeout"},
        {"unanswerable": True, "abstained": True},
        {"unanswerable": True, "error": "timeout", "abstained": False},
    ])
    assert aggregate["full_rubric_match_rate"] == 0.5
    assert aggregate["correct_abstention_rate"] == 0.5
    assert aggregate["errors"] == 2


def test_snapshot_does_not_change_database_or_copy_account_data(tmp_path):
    database = tmp_path / "source.db"
    with sqlite3.connect(database) as db:
        db.executescript("""
            CREATE TABLE research_spaces(id TEXT, user_id TEXT);
            CREATE TABLE papers(id TEXT, owner_id TEXT, title TEXT, source TEXT, ingest_status TEXT);
            CREATE TABLE pins(space_id TEXT, paper_id TEXT);
            CREATE TABLE chunks(paper_id TEXT, page INTEGER, section TEXT, text TEXT, ordinal INTEGER);
            CREATE TABLE users(email TEXT, password_hash TEXT);
            INSERT INTO research_spaces VALUES ('s','private-owner');
            INSERT INTO papers VALUES ('p','private-owner','A title','arxiv','READY');
            INSERT INTO pins VALUES ('s','p');
            INSERT INTO chunks VALUES ('p',1,'Introduction','Original source text.',0);
            INSERT INTO users VALUES ('private@example.test','DO-NOT-COPY');
        """)
    before = database.read_bytes()
    target = tmp_path / "corpus.json"
    snapshot(database, tmp_path / "uploads", target)
    assert database.read_bytes() == before
    assert "DO-NOT-COPY" not in target.read_text()
    assert "private-owner" not in target.read_text()
    assert load_corpus(target)[0].title == "A title"
    with pytest.raises(FileExistsError):
        snapshot(database, tmp_path, target)


def test_no_application_imports_and_no_run_path_escape():
    for path in ROOT.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith(("app.", "backend.", "frontend."))
    with pytest.raises(ValueError):
        safe_run(r"..\backend")


def test_multiline_table_cells_preserve_numeric_row_associations():
    rows, ambiguous = table_rows([
        ["Model", "Accuracy"], ["Model A\nModel B\nModel C", "71.0\n80.0\n95.0"],
    ])
    assert rows == [["Model", "Accuracy"], ["Model A", "71.0"], ["Model B", "80.0"], ["Model C", "95.0"]]
    assert not ambiguous
    _, ambiguous = table_rows([["Model A\nModel B", "95.0"]])
    assert ambiguous


def test_reference_audit_is_strategy_blind_and_does_not_leak_regex_rubric():
    from chat_chunking.audits.reference_audit import reference_payload
    doc = document()
    case = {"gold_groups": [[{"doc_id": doc.doc_id, "start": 0, "end": 12}]],
            "concepts": ["SECRET-RUBRIC"]}
    row = {"question": "What is observed?", "strategy": "baseline", "unanswerable": False,
           "claims": [{"text": "An observation", "cited_chunk_ids": ["id"]}],
           "contexts": [{"chunk_id": "id", "title": doc.title, "text": "A scientific observation."}]}
    payload = reference_payload(case, {doc.doc_id: doc}, row)
    assert "SECRET-RUBRIC" not in json.dumps(payload)
    assert "baseline" not in json.dumps(payload)
    assert payload["answer"] == ["An observation"]


def test_full_pdf_sources_only_use_approved_public_repositories():
    from chat_chunking.full_pdf import validate_url
    for source in json.loads((ROOT / "pdf_sources.json").read_text())["documents"]:
        validate_url(source["pdf_url"])
    for url in ["http://arxiv.org/pdf/1", "https://localhost/paper.pdf",
                "https://arxiv.org.evil.test/pdf/1", "https://user:password@arxiv.org/pdf/1"]:
        with pytest.raises(ValueError):
            validate_url(url)


def test_pdf_download_rejects_html_and_does_not_follow_unapproved_redirect(tmp_path):
    import httpx
    from chat_chunking.full_pdf import fetch_pdf
    def html(request):
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"<html>login</html>")
    with httpx.Client(transport=httpx.MockTransport(html)) as client:
        with pytest.raises(ValueError, match="HTML"):
            fetch_pdf(client, "https://arxiv.org/pdf/example", tmp_path / "paper.pdf")
    assert not (tmp_path / "paper.pdf").exists()
    seen = []
    def redirect(request):
        seen.append(str(request.url))
        return httpx.Response(302, headers={"location": "https://localhost/private"})
    with httpx.Client(transport=httpx.MockTransport(redirect)) as client:
        with pytest.raises(ValueError, match="unapproved"):
            fetch_pdf(client, "https://arxiv.org/pdf/example", tmp_path / "paper.pdf")
    assert seen == ["https://arxiv.org/pdf/example"]


def test_pdf_audit_refuses_empty_pages_instead_of_claiming_complete_extraction(tmp_path):
    from pypdf import PdfWriter
    from chat_chunking.full_pdf import audit_pdf
    path = tmp_path / "blank.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(path)
    with pytest.raises(ValueError, match="identity"):
        audit_pdf(path, "A real paper title", [])


def test_run_scoped_inputs_are_frozen_and_cannot_escape(tmp_path):
    from chat_chunking.benchmark import freeze_input, input_paths
    corpus, cases = input_paths(tmp_path, {"corpus_file": "inputs/corpus.json",
                                         "case_spec_file": "inputs/cases.json"})
    assert corpus.parent == tmp_path / "inputs"
    freeze_input(corpus, {"source": "unchanged"})
    freeze_input(corpus, {"source": "unchanged"})
    with pytest.raises(ValueError, match="replace"):
        freeze_input(corpus, {"source": "different"})
    with pytest.raises(ValueError, match="within"):
        input_paths(tmp_path, {"corpus_file": "../database.json", "case_spec_file": "cases.json"})


def test_full_pdf_case_adaptation_preserves23_original_questions_and_rubrics():
    from chat_chunking.full_pdf_cases import definitions
    original = json.loads((ROOT / "cases.json").read_text())
    updated = definitions(original)
    assert len(updated["cases"]) == 24
    assert sum(c["split"] == "calibration" for c in updated["cases"]) == 8
    for old, new in zip(original["cases"], updated["cases"], strict=True):
        assert new["id"] == old["id"] and new["split"] == old["split"]
        if old["id"] != "q19":
            assert new["question"] == old["question"]
            assert new["concepts"] == old["concepts"]
            assert new.get("unanswerable") == old.get("unanswerable")
    assert original["cases"][18]["category"] == "web_capture"


def test_semantic_chunking_bounds_oversized_pdf_paragraphs_without_losing_text():
    doc = Document("long-pdf", "Mathematical Research", "original_full_pdf", [
        Block("Mathematical notation α β γ and definitions. " * 800, 3, "Methods")
    ])
    doc.finalize()
    seen = []
    def bounded_embed(texts):
        seen.extend(texts)
        assert all(tokens(t) <= 800 for t in texts)
        return embed(texts)
    chunks = chunk_documents([doc], "hierarchical_semantic_structured", bounded_embed)
    assert len(seen) > 1
    assert "".join(seen) == doc.text
    assert covered({"doc_id": doc.doc_id, "start": 0, "end": len(doc.text)}, chunks.children)


def test_numeric_invariant_cannot_be_overridden_by_a_high_model_score():
    from chat_chunking.audits.numeric_checks import check_glove_total
    wrong = check_glove_total([{"text": "The total accuracy is75.9%."},
                              {"text": "The total accuracy is81.9 percent."}])
    assert wrong["wrong_explicit_numeric_assertion"]
    assert wrong["explicit_answer_percentages"] == [75.9, 81.9]
    assert not wrong["expected_value_present"]
    correct = check_glove_total([{"text": "The300-dimensional model on42B tokens has75.0% total accuracy."}])
    assert correct["expected_value_present"] and not correct["wrong_explicit_numeric_assertion"]
    assert not check_glove_total([])["expected_value_present"]
