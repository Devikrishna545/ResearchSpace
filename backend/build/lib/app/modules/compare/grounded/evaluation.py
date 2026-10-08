"""Evaluation metrics for grounded compare (plan section 19).

Each metric is computed separately so parser defects, model failures and
source-extraction failures are never merged into one number. Gold sets and
acceptance thresholds come from faculty reviewers; nothing here sets them.
"""

import re
from dataclasses import dataclass, field

from app.modules.compare.grounded.numerics import dataset_key

MODEL_FAILURES = {"model_error", "model_invalid_json", "model_empty"}


def _key(value: str) -> str:
    return dataset_key(value)


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


@dataclass
class PairResult:
    pair_id: str
    metrics: dict = field(default_factory=dict)
    counts: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def call_metrics(parse_statuses: list[str]) -> dict:
    total = len(parse_statuses)
    defects = parse_statuses.count("parser_defect")
    failures = sum(s in MODEL_FAILURES for s in parse_statuses)
    valid_json = total - sum(s in {"model_error", "model_invalid_json"} for s in parse_statuses)
    return {"llm_calls": total, "parser_shape_success": _ratio(valid_json - defects, valid_json),
            "parser_defects": defects, "model_failure_rate": _ratio(failures, total)}


def fact_metrics(report: dict, gold_pair: dict) -> dict:
    """Fact-type, ownership and dimension precision/recall against gold facts keyed by label (P1, P2, ...)."""
    out: dict = {}
    label_ids = report.get("paper_label_ids") or {}
    all_facts = [f for pid in label_ids.values() for f in (report["evidence_ledger"].get(pid, []) + report["audit_record"].get(pid, []))]
    resolved = [f for f in all_facts if "source_id_unresolved" not in f["validation_notes"]]
    out["source_id_resolution"] = _ratio(len(resolved), len(all_facts))
    quoted = [f for f in resolved if any(n.startswith(("exact_quote", "fuzzy_quote")) for n in f["validation_notes"])]
    out["quote_fidelity"] = _ratio(len(quoted), len(resolved))
    tp = fp = fn = owner_errors = dimension_errors = 0
    for label, pid in label_ids.items():
        gold = (gold_pair.get("facts") or {}).get(label, {})
        validated = report["evidence_ledger"].get(pid, [])
        for fact_type, expected in gold.items():
            expected_keys = {_key(v) for v in expected.get("values", [])}
            traps = {_key(v) for v in expected.get("not_owned", [])}
            off_dimension = {_key(v) for v in expected.get("wrong_type", [])}
            got = [f for f in validated if f["fact_type"] == fact_type]
            got_keys = {_key(f["value"]) for f in got}
            tp += len(got_keys & expected_keys)
            fp += len(got_keys - expected_keys)
            fn += len(expected_keys - got_keys)
            owner_errors += len(got_keys & traps)
            dimension_errors += len(got_keys & off_dimension)
    validated_total = tp + fp
    out.update({"fact_type_precision": _ratio(tp, validated_total), "fact_type_recall": _ratio(tp, tp + fn),
                "fact_ownership_precision": _ratio(validated_total - owner_errors, validated_total),
                "dimension_relevance": _ratio(validated_total - dimension_errors, validated_total)})
    return out


def _matches(finding: dict, expected: dict) -> bool:
    if expected.get("dimension") and finding["dimension"] != expected["dimension"]:
        return False
    text = _key(finding["statement"])
    return all(_key(k) in text for k in expected.get("keywords", []))


def finding_metrics(report: dict, gold_pair: dict) -> dict:
    sections = report["sections"]
    commons = [f for f in sections["commonalities"]]
    gold_commons = gold_pair.get("commonalities", [])
    true_commons = [f for f in commons if any(_matches(f, g) for g in gold_commons)]
    contradictions = [f for f in sections["contradictions"] if f["kind"] == "direct_contradiction_candidate"]
    gold_contra = gold_pair.get("contradictions", [])
    true_contra = [f for f in contradictions if any(_matches(f, g) for g in gold_contra)]
    numeric = [f for f in sections["numerical"] if f["kind"] == "numeric_comparison"]
    numeric_ok = numeric_checked = 0
    for expected in gold_pair.get("numeric", []):
        match = next((f for f in numeric if _matches(f, expected)), None)
        if match is None:
            continue
        numeric_checked += 1
        field_name = expected.get("field", "difference_percentage_points")
        value = (match.get("computed") or {}).get(field_name)
        if value is not None and abs(float(value) - float(expected["value"])) <= float(expected.get("tolerance", 1e-6)):
            numeric_ok += 1
    gaps = sections["candidate_gaps"]
    accepted = gold_pair.get("accepted_gaps", [])
    good_gaps = [g for g in gaps if any((not a.get("category") or a["category"] == g.get("category")) and _matches({**g, "dimension": g["dimension"]}, {"keywords": a.get("keywords", [])}) for a in accepted)]
    abstain_expected = gold_pair.get("expected_insufficient", {})
    table = {row["dimension"]: row for row in report["deterministic_table"]}
    abstained = sum(1 for label, dims in abstain_expected.items() for d in dims
                    if (table.get(d, {}).get("cells", {}).get(label) or {}).get("status") != "evidenced")
    expected_abstentions = sum(len(d) for d in abstain_expected.values())
    unrelated = bool(gold_pair.get("unrelated"))
    return {
        "commonality_precision": _ratio(len(true_commons), len(commons)),
        "false_cross_paper_agreement_rate": _ratio(len(commons) - len(true_commons), len(commons)) if not unrelated else _ratio(len(commons), max(1, len(commons))),
        "contradiction_precision": _ratio(len(true_contra), len(contradictions)),
        "numerical_calculation_accuracy": _ratio(numeric_ok, numeric_checked),
        "gap_precision": _ratio(len(good_gaps), len(gaps)) if accepted or gaps else None,
        "appropriate_abstention_rate": _ratio(abstained, expected_abstentions),
    }


def evaluate_pair(pair_id: str, report: dict, gold_pair: dict, parse_statuses: list[str], latency_s: float | None) -> PairResult:
    result = PairResult(pair_id=pair_id)
    result.metrics.update(call_metrics(parse_statuses))
    result.metrics.update(fact_metrics(report, gold_pair))
    result.metrics.update(finding_metrics(report, gold_pair))
    result.metrics["latency_s"] = latency_s
    extraction_flags = [flag for p in report["papers"] for flag in p["build"]["quality_flags"]]
    result.counts = {"source_extraction_flags": len(extraction_flags), "withheld": report.get("withheld_count", 0)}
    result.notes = sorted(set(re.sub(r":.*", "", f) for f in extraction_flags))
    return result


def aggregate(results: list[PairResult]) -> dict:
    keys = sorted({k for r in results for k in r.metrics})
    summary = {}
    for key in keys:
        values = [r.metrics[key] for r in results if isinstance(r.metrics.get(key), (int, float))]
        summary[key] = round(sum(values) / len(values), 4) if values else None
    return summary


def release_gate(summary: dict, thresholds: dict) -> dict:
    """Compare against faculty-approved thresholds.

    Proposed engineering thresholds are useful for dry runs but cannot authorize
    release until faculty explicitly approve them.
    """
    checks = {}
    for metric, rule in thresholds.items():
        if metric.startswith("_"):
            continue
        value = summary.get(metric)
        minimum, maximum = (rule or {}).get("min"), (rule or {}).get("max")
        if value is None or (minimum is None and maximum is None):
            checks[metric] = {"value": value, "passed": None, "reason": "threshold not set by faculty or metric unavailable"}
            continue
        passed = (minimum is None or value >= minimum) and (maximum is None or value <= maximum)
        checks[metric] = {"value": value, "passed": passed, "min": minimum, "max": maximum}
    faculty_approved = thresholds.get("_faculty_approved") is True
    passed = faculty_approved and bool(checks) and all(c["passed"] is True for c in checks.values())
    reason = None if faculty_approved else "thresholds are an engineering draft awaiting faculty approval"
    return {"passed": passed, "faculty_approved": faculty_approved, "reason": reason, "checks": checks}
