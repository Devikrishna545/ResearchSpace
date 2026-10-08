"""Deterministic paired analysis of completed runs, with changed questions excluded."""

from __future__ import annotations

from collections import Counter

import numpy as np

from ..benchmark import safe_run, verify_manifest
from ..chunking import STRATEGIES
from ..corpus import ROOT, digest, read_json, write_json
from ..evaluation import passes, summary


def correct_complete(row: dict) -> bool:
    return row.get("status") == "CORRECT" and row.get("complete") is True


def paired_interval(differences: list[float]) -> dict:
    values = np.asarray(differences, dtype=np.float64)
    if not values.size:
        raise ValueError("No paired questions available.")
    samples = np.random.default_rng(42).integers(0, len(values), size=(10000, len(values)))
    return {"difference": float(values.mean()), "question_count": len(values),
            "paired_question_bootstrap_95_interval": np.quantile(
                values[samples].mean(axis=1), [0.025, 0.975]).tolist()}


def main() -> dict:
    name = "fullpdf-20261002-v2"
    old_name = "pilot-20261002-v2"
    run = safe_run(name)
    old_run = safe_run(old_name)
    manifest = verify_manifest(run)
    old_manifest = read_json(old_run / "manifest.json")
    if manifest["models"] != old_manifest["models"] or manifest["config"] != old_manifest["config"]:
        raise ValueError("Models or controls differ between pilots; not a controlled model comparison.")
    rows = [read_json(p) for p in sorted((run / "results").glob("*.json"))]
    old_rows = [read_json(p) for p in sorted((old_run / "results").glob("*.json"))]
    if len(rows) != 96 or len(old_rows) != 96:
        raise ValueError("Both primary runs must contain all96 records.")
    audit = read_json(ROOT / "reports" / name / "reference_audit.json")
    old_audit = read_json(ROOT / "reports" / old_name / "reference_audit.json")
    if len(audit["per_question"]) != 96 or len(old_audit["per_question"]) != 96:
        raise ValueError("Both reference audits must be complete.")
    before_cases = {c["id"]: c for c in read_json(old_run / "cases.json")}
    after_cases = {c["id"]: c for c in read_json(run / "cases.json")}
    common = {cid for cid, c in before_cases.items() if all(
        c.get(key) == after_cases[cid].get(key)
        for key in ("question", "concepts", "forbidden", "split", "unanswerable")
    )}
    if len(common) != 23 or "q19" in common:
        raise ValueError("Expected23 unchanged question/rubric pairs, with q19 excluded.")
    by = {(r["strategy"], r["case_id"]): r for r in rows}
    old_by = {(r["strategy"], r["case_id"]): r for r in old_rows}
    judged = {(r["strategy"], r["case_id"]): r for r in audit["per_question"]}
    old_judged = {(r["strategy"], r["case_id"]): r for r in old_audit["per_question"]}
    ids = sorted(cid for cid in common if after_cases[cid]["split"] == "held_out"
                 and not after_cases[cid].get("unanswerable"))
    comparisons = {}
    within = {}
    acceptance = {}
    chosen = read_json(ROOT / "reports" / name / "summary.json")["threshold_selection"]
    for strategy in STRATEGIES:
        before = [old_by[strategy, cid] for cid in ids]
        after = [by[strategy, cid] for cid in ids]
        comparisons[strategy] = {
            "before": summary(before), "after": summary(after),
            "reference_audit_before": sum(correct_complete(old_judged[strategy, cid]) for cid in ids) / len(ids),
            "reference_audit_after": sum(correct_complete(judged[strategy, cid]) for cid in ids) / len(ids),
            "audit_accuracy_difference": paired_interval([
                float(correct_complete(judged[strategy, cid])) -
                float(correct_complete(old_judged[strategy, cid])) for cid in ids]),
            "evidence_recall_difference": paired_interval([
                by[strategy, cid]["evidence_recall"] -
                old_by[strategy, cid]["evidence_recall"] for cid in ids]),
        }
        held = [r for r in rows if r["strategy"] == strategy and r["split"] == "held_out"]
        gates = {}
        for label, score, cosine in (("reference", 0.9, 0.65),
                                     ("calibration_selected", chosen["review_threshold"], chosen["similarity_threshold"])):
            accepted = [r for r in held if passes(r, score, cosine)]
            gates[label] = {
                "review_threshold": score, "similarity_threshold": cosine,
                "accepted": len(accepted), "attempts": len(held),
                "audited_correct_complete": sum(correct_complete(judged[r["strategy"], r["case_id"]]) for r in accepted),
                "accepted_case_ids": [r["case_id"] for r in accepted],
            }
        acceptance[strategy] = gates
        new_ids = sorted(r["case_id"] for r in held if not r["unanswerable"])
        within[strategy] = {
            "audit_accuracy_vs_baseline": paired_interval([
                float(correct_complete(judged[strategy, cid])) -
                float(correct_complete(judged["baseline", cid])) for cid in new_ids]),
            "evidence_recall_vs_baseline": paired_interval([
                by[strategy, cid]["evidence_recall"] -
                by["baseline", cid]["evidence_recall"] for cid in new_ids]),
        }
    data = {
        "method": "10000 paired-question bootstrap resamples, seed42; exploratory, unadjusted for multiple comparisons, one generation per question",
        "comparison_limit": "Fresh extraction, larger full-text corpus and one replaced document change retrieval competition. These deltas do not isolate extraction as the sole cause.",
        "common_question_ids": sorted(common), "excluded_case_ids": ["q19"],
        "common_held_out_answerable_ids": ids,
        "comparisons_to_saved_text_pilot": comparisons,
        "within_full_pdf_vs_baseline": within,
        "strict_held_out_gate_reference_audit": acceptance,
        "claim_statuses": {s: dict(Counter(c["status"] for r in rows if r["strategy"] == s
                                          for c in r.get("review_claims", []))) for s in STRATEGIES},
        "primary_claims": sum(r.get("claim_count", 0) for r in rows),
        "primary_citations": sum(r.get("citation_count", 0) for r in rows),
    }
    out = ROOT / "reports" / name
    write_json(out / "paired_analysis.json", data)
    corpus = read_json(run / "inputs" / "corpus.json")
    write_json(out / "extraction_audit.json", {
        "corpus_sha256": corpus["sha256"], "corpus_file_sha256": digest(corpus),
        "documents": [{k: v for k, v in row.items() if k != "identity_pattern"}
                      for row in corpus["source_checks"]],
    })
    print("COMMON_QUESTIONS", len(common), "COMMON_HELDOUT_ANSWERABLE", len(ids))
    for strategy in STRATEGIES:
        print(strategy, "heldout", summary([r for r in rows if r["strategy"] == strategy and r["split"] == "held_out"]),
              "audit", audit["strategies"][strategy]["held_out"],
              "gates", acceptance[strategy])
    return data


if __name__ == "__main__":
    main()
