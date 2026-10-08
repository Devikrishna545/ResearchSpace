# QASPER + PDF validation

**Status:** Completed1800 attempts.

Answer/Evidence F1 use official QASPER scoring rules; source-checked PDF labels are not human gold.
No production changes. Accepted-answer95% safety is not certified; human adjudication remains pending.

| Arm | Track | Held-out attempts | Answer F1 | Evidence F1 | Claim support | Median path seconds |
|---|---|---:|---:|---:|---:|---:|
|current_chat|qasper|300|0.374|0.132|0.840|8.625|
|current_chat|pdf_supplement|180|0.281|0.063|0.638|8.604|
|baseline|qasper|300|0.333|0.078|0.844|8.840|
|baseline|pdf_supplement|180|0.371|0.061|0.683|8.979|
|research_aware|qasper|300|0.367|0.139|0.851|8.613|
|research_aware|pdf_supplement|180|0.415|0.065|0.677|9.054|

## Paired held-out QASPER comparison to current Chat word policy

- **baseline**: Answer F1 difference -0.0407, paired95% interval [-0.10590040443308145, 0.024544320599912507]; Evidence F1 difference -0.0540.
- **research_aware**: Answer F1 difference -0.0066, paired95% interval [-0.06653930909549563, 0.05404335699813649]; Evidence F1 difference 0.0075.

Seed repetitions were averaged before bootstrapping distinct QASPER papers. PDF supplement results remain source-checked, not human-certified. Index failures, alignment limits, judge errors and pending human safety adjudication prevent automatic production promotion.
