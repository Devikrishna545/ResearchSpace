from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from statistics import mean

import numpy as np

from chat_chunking.corpus import read_json, write_json
from qasper_validation.chunkers import ARMS
from qasper_validation.data import ROOT
from qasper_validation.runner import SEEDS, run_path, verify


def paired_question_interval(differences: list[float]) -> dict:
    values = np.asarray(differences)
    if len(values) < 2:
        return {"difference": float(values.mean()) if len(values) else None,
                "interval": None, "reason": "Insufficient independent question clusters."}
    draws = np.random.default_rng(42).integers(0, len(values), size=(10000, len(values)))
    return {"difference": float(values.mean()),
            "bootstrap95_interval": np.quantile(values[draws].mean(axis=1), [0.025, 0.975]).tolist(),
            "independent_question_clusters": len(values)}


def main(name: str) -> dict:
    run = run_path(name)
    verify(run)
    data = read_json(run / "inputs.json")
    cases = {c["case_id"]: c for c in data["cases"]}
    rows = [read_json(p) for p in (run / "results").glob("*.json")]
    expected = {(a, c, s) for a in ARMS for c in cases for s in SEEDS}
    keyed = {(r["arm"], r["case_id"], r["seed"]): r for r in rows}
    if len(rows) != 1800 or set(keyed) != expected:
        raise ValueError("Require exactly the registered1800 arm/question/seed records.")
    ids = sorted(c for c, case in cases.items() if case["track"] == "qasper" and case["split"] == "held_out")
    if len(ids) != 100:
        raise ValueError("Expected100 independent held-out QASPER papers.")
    confidence = {}
    for arm in ARMS[1:]:
        confidence[arm] = {}
        for field in ("answer_f1", "evidence_f1"):
            differences = [
                mean(keyed[arm, c, s].get(field, 0) for s in SEEDS) -
                mean(keyed["current_chat", c, s].get(field, 0) for s in SEEDS)
                for c in ids
            ]
            confidence[arm][field] = paired_question_interval(differences)
    per_category = {}
    for arm in ARMS:
        per_category[arm] = {}
        for category in sorted({r["category"] for r in rows if r["split"] == "held_out"}):
            selected = [r for r in rows if r["arm"] == arm and r["category"] == category and r["split"] == "held_out"]
            per_category[arm][category] = {
                "attempts": len(selected), "errors": sum(bool(r.get("error")) for r in selected),
                "answer_f1": mean(r.get("answer_f1", 0) for r in selected),
                "evidence_f1": mean(r.get("evidence_f1", 0) for r in selected),
            }
    repeated = {}
    for arm in ARMS:
        per_case = [[keyed[arm, c, s].get("answer", "") for s in SEEDS] for c in cases]
        repeated[arm] = {"identical_across_three_seeds": sum(len(set(v)) == 1 for v in per_case),
                         "questions": 200, "temperature": 0,
                         "note": "Seeds do not guarantee independent stochastic answers at temperature0."}
    model_loading = {}
    numeric_including_failures = {}
    for arm in ARMS:
        selected = [r for r in rows if r["arm"] == arm]
        model_loading[arm] = {
            "answer_load_seconds_total": sum(r.get("answer_load_seconds", 0) for r in selected),
            "review_load_seconds_total": sum(r.get("review_load_seconds", 0) for r in selected),
            "note": "Provider load times are included in request wall times; not a controlled cold-model experiment.",
        }
        eligible = [r for r in selected if r["split"] == "held_out"
                    and cases[r["case_id"]].get("numeric_regex")]
        numeric_including_failures[arm] = {
            "attempts": len(eligible),
            "passed": sum(r.get("numeric_check_pass") is True and not r.get("error") for r in eligible),
            "failure_inclusive_pass_rate": sum(r.get("numeric_check_pass") is True and not r.get("error")
                                               for r in eligible) / len(eligible) if eligible else None,
            "scope": "Supplementary registered numerical checks; missing/error outcomes count as failures.",
        }
    result = {
        "complete": True, "unique_records": 1800,
        "errors": sum(bool(r.get("error")) for r in rows),
        "qasper_heldout_paired_to_current_control": confidence,
        "bootstrap_method": "10000 paired resamples over100 distinct held-out QASPER papers; seed repetitions averaged first; no multiple-comparison adjustment",
        "supplement_confidence_limit": "Four held-out PDF documents with cross-paper questions are not60 independent source clusters; no narrow question-bootstrap interval claimed.",
        "per_category": per_category, "seed_repetition": repeated, "provider_model_loading": model_loading,
        "numeric_checks_including_errors": numeric_including_failures,
        "safety_target95_percent": "Cannot certify until accepted-answer human_adjudication_queue is completed.",
    }
    output = ROOT / "reports" / name
    write_json(output / "uncertainty_and_diagnostics.json", result)
    accepted = read_json(run / "human_adjudication_queue.json")
    write_json(run / "human_adjudication_pack.json", [
        {**row, "question": cases[row["case_id"]]["question"],
         "reference_annotations": cases[row["case_id"]]["references"],
         "label_provenance": cases[row["case_id"]]["label_provenance"],
         "independently_correct_and_complete": None}
        for row in accepted
    ])
    with (output / "REPORT.md").open("a", encoding="utf-8") as stream:
        stream.write("\n## Paired held-out QASPER comparison to current Chat word policy\n\n")
        for arm, metrics in confidence.items():
            stream.write(f"- **{arm}**: Answer F1 difference {metrics['answer_f1']['difference']:.4f}, "
                         f"paired95% interval {metrics['answer_f1'].get('bootstrap95_interval')}; "
                         f"Evidence F1 difference {metrics['evidence_f1']['difference']:.4f}.\n")
        stream.write("\nSeed repetitions were averaged before bootstrapping distinct QASPER papers. "
                     "PDF supplement results remain source-checked, not human-certified. "
                     "Index failures, alignment limits, judge errors and pending human safety adjudication prevent automatic production promotion.\n")
    print(result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", default="qasper-pdf-20261002-v2")
    main(parser.parse_args().run)
