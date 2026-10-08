"""Check an explicit table-value invariant independently of the language-model judge."""

from __future__ import annotations

import re
from decimal import Decimal

from ..benchmark import safe_run, verify_manifest
from ..corpus import ROOT, read_json, write_json


def check_glove_total(claims: list[dict]) -> dict:
    values = [Decimal(match.group(1)) for claim in claims
              for match in re.finditer(r"(?<![\d.])(\d+(?:\.\d+)?)\s*(?:%|percent\b)",
                                       claim["text"], re.I)]
    return {
        "expected_total_accuracy_percent": 75.0,
        "explicit_answer_percentages": [float(v) for v in values],
        "wrong_explicit_numeric_assertion": any(v != Decimal("75.0") for v in values),
        "expected_value_present": Decimal("75.0") in values,
        "scope": "q04 asks one total percentage; explicit other percentage assertions are wrong for that requested field. Missing/word-spelled percentages are not automatically declared correct.",
    }


def main() -> dict:
    name = "fullpdf-20261002-v2"
    run = safe_run(name)
    verify_manifest(run)
    cases = read_json(run / "cases.json")
    case = next(c for c in cases if c["id"] == "q04")
    if case["split"] != "calibration":
        raise ValueError("The numeric check's registered case changed.")
    records = []
    for path in sorted((run / "results").glob("*-q04.json")):
        row = read_json(path)
        audit = read_json(run / "reference_audit" / "results" / path.name)
        check = check_glove_total(row.get("claims", []))
        records.append({
            "strategy": row["strategy"], "case_id": "q04", "split": case["split"],
            **check, "model_audit_status": audit.get("status"),
            "confirmed_audit_false_positive": check["wrong_explicit_numeric_assertion"]
                                             and audit.get("status") == "CORRECT",
        })
    if len(records) != 4:
        raise ValueError("Expected all four q04 answers.")
    result = {"kind": "post_hoc_explicit_numeric_invariant_not_replacement_accuracy_metric",
              "primary_metrics_and_thresholds_unchanged": True, "records": records}
    write_json(ROOT / "reports" / name / "numeric_consistency.json", result)
    print(result)
    return result


if __name__ == "__main__":
    main()
