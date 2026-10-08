from app.modules.compare.grounded.evaluation import aggregate, call_metrics, evaluate_pair, release_gate


def _fact(fid, pid, fact_type, value, notes=("exact_quote",)):
    return {"fact_id": fid, "paper_id": pid, "fact_type": fact_type, "value": value, "validation_notes": list(notes)}


def _report():
    return {
        "paper_label_ids": {"P1": "a", "P2": "b"},
        "papers": [{"build": {"quality_flags": ["ocr_uncertain"]}}, {"build": {"quality_flags": []}}],
        "evidence_ledger": {"a": [_fact("1", "a", "dataset", "Google News corpus"), _fact("2", "a", "dataset", "CBOW architecture")],
                            "b": [_fact("3", "b", "dataset", "Wikipedia 2014")]},
        "audit_record": {"a": [_fact("4", "a", "dataset", "X", notes=("source_id_unresolved",))], "b": []},
        "sections": {
            "commonalities": [{"dimension": "metric", "statement": "All selected papers report the metric “accuracy”.", "kind": "commonality"},
                              {"dimension": "dataset", "statement": "Both report Google News.", "kind": "commonality"}],
            "differences": [], "contradictions": [],
            "numerical": [{"kind": "numeric_comparison", "dimension": "result", "statement": "On SST-2, accuracy differs",
                           "computed": {"difference_percentage_points": 3.3}}],
            "candidate_gaps": [{"dimension": "generalizability_gap", "category": "generalizability_gap", "statement": "Neither paper evaluates non-English text."}],
        },
        "deterministic_table": [{"dimension": "population", "cells": {"P1": {"status": "insufficient_evidence"}, "P2": {"status": "evidenced"}}}],
        "withheld_count": 2,
    }


GOLD = {
    "facts": {"P1": {"dataset": {"values": ["Google News corpus"], "wrong_type": ["CBOW architecture"]}},
              "P2": {"dataset": {"values": ["Wikipedia 2014", "Gigaword 5"]}}},
    "commonalities": [{"dimension": "metric", "keywords": ["accuracy"]}],
    "numeric": [{"dimension": "result", "keywords": ["sst"], "value": 3.3, "tolerance": 0.01}],
    "accepted_gaps": [{"category": "generalizability_gap", "keywords": ["english"]}],
    "expected_insufficient": {"P1": ["population"], "P2": ["population"]},
}


def test_metrics_are_separate_and_exact():
    result = evaluate_pair("pair", _report(), GOLD, ["ok", "normalized", "parser_defect", "model_error", "not_found"], 12.0)
    m = result.metrics
    assert m["parser_defects"] == 1 and m["parser_shape_success"] == 0.75 and m["model_failure_rate"] == 0.2
    assert m["source_id_resolution"] == 0.75 and m["quote_fidelity"] == 1.0
    assert m["fact_type_precision"] == round(2 / 3, 4) and m["fact_type_recall"] == round(2 / 3, 4)
    assert m["dimension_relevance"] == round(2 / 3, 4)
    assert m["commonality_precision"] == 0.5 and m["false_cross_paper_agreement_rate"] == 0.5
    assert m["numerical_calculation_accuracy"] == 1.0 and m["gap_precision"] == 1.0
    assert m["appropriate_abstention_rate"] == 0.5
    assert result.counts["source_extraction_flags"] == 1


def test_release_gate_cannot_pass_without_faculty_thresholds():
    summary = aggregate([evaluate_pair("p", _report(), GOLD, ["ok"], 1.0)])
    assert release_gate(summary, {"fact_type_precision": {"min": None}})["passed"] is False
    proposed = release_gate(summary, {"_faculty_approved": False, "fact_type_precision": {"min": 0.5}})
    assert proposed["passed"] is False and proposed["faculty_approved"] is False
    approved = {"_faculty_approved": True, "fact_type_precision": {"min": 0.5},
                "false_cross_paper_agreement_rate": {"max": 0.6}}
    assert release_gate(summary, approved)["passed"] is True
    assert release_gate(summary, {"_faculty_approved": True, "false_cross_paper_agreement_rate": {"max": 0.1}})["passed"] is False
    assert call_metrics([])["parser_shape_success"] is None
