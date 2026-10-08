# Grounded compare evaluation

This folder holds the evaluation inputs for the grounded Compare module
(`grounded_compare_implementation_plan.md`, section 19).

| File | Owner | Purpose |
|---|---|---|
| `gold_template.json` | engineering | Shape of a gold set. Copy it to `gold.json`. |
| `gold.json` | engineering draft → faculty reviewers | Populated from local papers but explicitly unapproved. Review every label, cover `draft_gaps`, then set `"faculty_approved": true`. |
| `thresholds.json` | engineering draft → faculty reviewers | Conservative proposed thresholds. Review them, then set `"_faculty_approved": true`; until then the release gate cannot pass. |

## What a gold pair needs

Cover the cases from the plan: real agreement, genuine contradictions,
apparent contradictions (different datasets or metrics), unrelated papers,
tables and figures, scanned PDFs, missing limitations or datasets,
related-work mentions (ownership traps), and architecture-versus-dataset or
method-versus-metric traps.

Per pair, keyed by paper label (`P1`, `P2`, … in sorted paper-ID order):

- `facts.<label>.<fact_type>.values`: facts the paper really states about its own work.
- `wrong_type`: plausible values of another type (for example, `CBOW architecture` as a dataset).
- `not_owned`: values that appear only as cited or related work.
- `commonalities`, `contradictions`: `{dimension, keywords}` that a correct finding must match.
- `numeric`: `{dimension, keywords, field, value, tolerance}` for code-computed comparisons.
- `accepted_gaps`: `{category, keywords}` that reviewers accept.
- `expected_insufficient`: dimensions where the correct answer is "Insufficient evidence".
- `unrelated: true`: any shown commonality counts as a false cross-paper agreement.

## Running

From `backend/`:

```powershell
python -m scripts.eval_grounded_compare --gold evaluations/compare/grounded/gold.json --owner-id <user id> --run --tier student --out evaluations/compare/grounded/results-student.json
```

Run the same gold set once per laptop tier to measure latency by tier.
Metrics are reported separately. Parser defects (`parser_shape_success`,
`parser_defects`), model failures (`model_failure_rate`), and
source-extraction problems (`source_extraction_flags`) are never merged.
