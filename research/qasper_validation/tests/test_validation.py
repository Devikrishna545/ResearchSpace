import importlib.util
from pathlib import Path

import numpy as np
import pytest

from chat_chunking.corpus import Block, Document
from qasper_validation.chunkers import build, current_word_helper
from qasper_validation.data import RAW, annotation, paper_document, resolve_evidence
from qasper_validation.scoring import answer_f1, evidence_f1, score_case, validate_generated
from qasper_validation.runner import CONFIG, SEEDS, aggregate, passes, run_path, validate_data


def official():
    path = RAW / "evaluator.py"
    if not path.exists():
        pytest.fail("Download the official evaluator before running validation tests.")
    spec = importlib.util.spec_from_file_location("qasper_official", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("prediction,reference", [
    ("The A model.", "a model"), ("Yes", "No"), ("Yes", "yes"),
    ("", ""), ("Unanswerable", "Unanswerable"),
    ("75.0%", "75%"), ("blue blue red", "blue red red"),
    ("alpha and beta", "beta, alpha"), ("The system uses300 samples", "300"),
])
def test_answer_f1_matches_official_script(prediction, reference):
    assert answer_f1(prediction, reference) == pytest.approx(
        official().token_f1_score(prediction, reference))


@pytest.mark.parametrize("prediction,reference", [
    ([], []), (["p1"], []), ([], ["p1"]), (["p1", "p2"], ["p2"]),
    (["same", "same"], ["same"]), (["a"], ["b"]),
])
def test_evidence_f1_matches_official_duplicates_and_empty_handling(prediction, reference):
    assert evidence_f1(prediction, reference) == pytest.approx(
        official().paragraph_f1_score(prediction, reference))


def test_qasper_annotation_types_preserve_no_and_unanswerable():
    base = {"unanswerable": False, "extractive_spans": [], "free_form_answer": "",
            "yes_no": False, "evidence": []}
    assert annotation(base)["answer"] == "No"
    assert annotation({**base, "unanswerable": True})["answer"] == "Unanswerable"
    with pytest.raises(ValueError):
        annotation({**base, "yes_no": None})


def test_heading_and_caption_evidence_align_without_changing_reference_labels():
    paper = {"title": "Research", "abstract": "An abstract.",
             "full_text": [{"section_name": "Methods ::: Setup", "paragraphs": ["We used300 samples."]}],
             "figures_and_tables": [{"caption": "Table1: Accuracy95%.", "file": "table.png"}]}
    doc, units = paper_document("p", paper)
    assert resolve_evidence("Methods ::: Setup", units) is not None
    assert resolve_evidence("FLOAT SELECTED: Table1: Accuracy95%.", units) is not None
    assert resolve_evidence("An abstract.", units) is not None
    assert resolve_evidence("invented source", units) is None
    for unit in units:
        assert doc.text[unit["start"]:unit["end"]].strip()


def test_current350_word_control_matches_actual_pure_helper():
    doc = Document("test", "Research", "test", [
        Block(" ".join(f"word{i}" for i in range(900)), 1, "Methods"),
        Block("A new section." * 10, 2, "Results"),
    ])
    doc.finalize()
    indexed = build([doc], "current_chat")
    expected = current_word_helper()(doc.blocks[0].text, size=350, overlap=50)
    assert [" ".join(c.text.split()) for c in indexed.children if c.page == 1] == expected
    assert len(indexed.children[0].text.split()) == 350
    assert indexed.children[0].text.split()[-50:] == indexed.children[1].text.split()[:50]
    assert all(len(c.text.split()) <= 350 for c in indexed.children)


def test_score_uses_best_of_all_references_and_exact_source_strings():
    doc = Document("p", "Paper", "test", [Block("Original evidence.", None, "Methods")])
    doc.finalize()
    context = build([doc], "baseline").children
    units = [{"unit_id": "p0", "original": "Original evidence.", "doc_id": "p", "start": 0, "end": len(doc.text)}]
    case = {"case_id": "q", "references": [
        {"answer": "wrong", "type": "extractive", "evidence": ["missing original"], "evidence_units": [None]},
        {"answer": "correct", "type": "extractive", "evidence": ["Original evidence."], "evidence_units": ["p0"]}],
        "alignment_missing": ["missing original"]}
    metrics = score_case(case, "correct", context,
                         [{"text": "Fact", "cited_chunk_ids": [context[0].chunk_id]}], units)
    assert metrics["answer_f1"] == 1 and metrics["evidence_f1"] == 1
    assert metrics["alignment_failure"]


def test_numeric_errors_cannot_pass_high_reviewer_score():
    row = {"claim_count": 1, "review_verdict": "APPROVED", "review_score": 1,
           "supported_claim_rate": 1, "quote_provenance_rate": 1,
           "citation_validity": 1, "min_citation_similarity": 1, "numeric_check_pass": False}
    assert not passes(row, 0.9, 0.65)
    assert passes({**row, "numeric_check_pass": True}, 0.9, 0.65)
    assert not passes({**row, "numeric_check_pass": True, "error": "timeout"}, 0.9, 0.65)


def test_generation_rejects_unsupported_ids_and_uncited_non_abstention():
    with pytest.raises(ValueError):
        validate_generated({"answer": "Fact", "claims": []}, {"real"})
    with pytest.raises(ValueError):
        validate_generated({"answer": "Fact", "claims": [{"text": "Fact", "cited_chunk_ids": ["fake"]}]}, {"real"})
    assert validate_generated({"answer": "Unanswerable", "claims": []}, {"real"}) == ("Unanswerable", [])


def test_failures_remain_in_score_denominators_and_safety_not_certified():
    result = aggregate([{"answer_f1": 1, "evidence_f1": 1, "answer_exact_match": True},
                        {"answer_f1": 0, "evidence_f1": 0, "error": "timeout"}])
    assert result["attempts"] == 2 and result["errors"] == 1
    assert result["answer_f1"] == 0.5
    assert "not established" in result["safety_certification"]


def test_registration_dimensions_and_run_path_safety():
    assert CONFIG["attempts"] == CONFIG["questions"] * len(CONFIG["arms"]) * len(SEEDS) == 1800
    with pytest.raises(ValueError):
        run_path(r"..\backend")


def test_frozen_dataset_has_correct_allocation_and_document_disjointness():
    from qasper_validation.data import load_dataset
    data = load_dataset()
    validate_data(data)
    assert len({d["doc_id"] for d in data["documents"]}) == 126
    assert not data["alignment_failed_case_ids"]
    assert all(c["label_provenance"].startswith("independent") for c in data["cases"] if c["track"] == "qasper")
    assert all("pending" in c["label_provenance"] for c in data["cases"] if c["track"] == "pdf_supplement")


def test_status_retries_only_transient_windows_file_locks(tmp_path, monkeypatch):
    from qasper_validation import runner
    calls = []
    original = runner.write_json
    def locked(path, data):
        calls.append(path)
        if len(calls) < 3:
            exc = PermissionError("Transient status-file sharing violation")
            exc.winerror = 32
            raise exc
        original(path, data)
    monkeypatch.setattr(runner, "write_json", locked)
    monkeypatch.setattr(runner, "sleep", lambda _: None)
    runner.progress(tmp_path, "testing")
    assert len(calls) == 3 and (tmp_path / "status.json").is_file()
    def permanent(path, data):
        raise PermissionError("Permanent denial")
    monkeypatch.setattr(runner, "write_json", permanent)
    with pytest.raises(PermissionError, match="Permanent"):
        runner.progress(tmp_path, "testing")
