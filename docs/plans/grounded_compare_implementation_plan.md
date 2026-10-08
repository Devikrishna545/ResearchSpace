# Grounded Compare: Complete Implementation Plan

## 1. Objective

Replace the current profile-only paper-comparison system with a local-first, evidence-grounded system. The product must compare two or more papers while preserving exact source provenance, abstaining when evidence is inadequate, calculating numerical results in code, and treating gap and novelty outputs as appropriately qualified candidates.

This plan is based on the documented current workflow and the measured findings in `backend/evaluations/compare/DECISION.md`.

## 2. Non-negotiable product rules

1. A generated profile is never treated as paper evidence.
2. Every displayed factual finding must resolve to a source span, page, and paper.
3. A real quote is not enough: it must support the claim and answer the requested comparison dimension.
4. A shared claim must have direct support from every paper named in that claim.
5. An empty result is better than an invented one. The interface must show `Insufficient evidence` when appropriate.
6. Numerical and statistical values are calculated or checked in Python, not trusted from an LLM response.
7. A two-paper comparison cannot prove novelty. Novelty needs broader-literature retrieval and coverage disclosure.
8. Embedding similarity is for retrieval only; it is not proof of factual support, entity type, or dimension relevance.

## 3. Current-state changes

| Current component | Current behavior | Replacement |
|---|---|---|
| `PaperProfile` | Seven free-text fields from at most 12,000 characters | Versioned evidence ledger containing typed, source-bound facts |
| Profile packing | Keyword selection and fixed character cap | Retrieval by task and dimension over page-aware chunks |
| `CompareAgent` | Compares profiles only | Compares validated facts and task-specific source evidence |
| `GapAgent` | Generates gaps from profiles | Generates candidate gaps from explicit missing/limited facts |
| Verification loop | Reviews a fixed draft against profile text | Verifies candidate claims against original source spans; unsupported claims are suppressed |
| Report confidence | One score / verified badge | Per-finding evidence status plus an honest report-level coverage summary |
| Refresh | Reuses stale paper profile | Rebuilds versioned evidence records and invalidates dependent results |
| HTTP request | Synchronous request with 180-second limit | Background job with progress, cancellation, and resumable results |

## 4. Local model stack

### Student-laptop default

```powershell
ollama pull qwen3:8b
ollama pull qwen3-vl:8b
ollama pull embeddinggemma:300m-qat-q4_0
```

| Model | Role | Constraints |
|---|---|---|
| `qwen3:8b` | Typed fact extraction, source-limited validation, candidate comparison, candidate-gap drafting | Use low temperature and strict JSON; never let it verify its own summary as evidence |
| `qwen3-vl:8b` | Selected tables, figures, equations, and scanned pages | Send only relevant rendered pages, not every PDF page |
| `embeddinggemma:300m-qat-q4_0` | Local semantic retrieval | Retrieval/ranking support only; never a fact-checking gate |
| Python (`pandas`, `NumPy`, `SciPy`) | Numeric, dataset, metric, and statistical analysis | Deterministic source of computed values |

### Weak-laptop fallback

```powershell
ollama pull qwen3:4b
ollama pull qwen3-vl:4b
```

This tier may produce summaries and candidate findings, but it should require more abstention and should not be used as a final evidence authority.

### University deep-review tier

```powershell
ollama pull qwen3:30b-thinking
ollama pull qwen3-vl:32b-thinking
ollama pull mistral-small3.1:24b
```

This is an optional server/lab-machine enhancement. It improves interpretation but does not replace evidence rules or evaluation.

### Versioning

Pin each deployed model tag and record model name, Ollama version, prompt version, seed, quantization, and parser version with every generated artifact. Do not depend on `latest` for reproducible academic output.

## 5. System architecture

```text
PDF upload
  → document validation and parsing
  → page-aware chunk / table / figure source graph
  → local embedding index
  → narrow typed-fact extraction per paper
  → type, ownership, and provenance validation
  → deterministic comparisons and numerical analysis
  → source-grounded candidate semantic comparisons
  → claim verification and suppression
  → candidate-gap analysis
  → optional broader-literature novelty retrieval
  → page-linked comparison report
```

## 6. Data model

### 6.1 Source artifacts

Create source artifacts before any LLM call.

```json
{
  "source_id": "paper-a-page-05-chunk-02",
  "paper_id": "paper-a",
  "kind": "text",
  "page_start": 5,
  "page_end": 5,
  "section": "Methods",
  "text": "…",
  "parser_version": "v2",
  "content_hash": "…"
}
```

For tables:

```json
{
  "source_id": "paper-a-table-02",
  "paper_id": "paper-a",
  "kind": "table",
  "page_start": 7,
  "label": "Table 2",
  "caption": "Performance across datasets",
  "cells": [["Method", "Accuracy"], ["Proposed", "91.3"]],
  "extraction_status": "parsed"
}
```

For figures, retain rendered-page image paths, captions, page number, and OCR text where available.

### 6.2 Evidence facts

Replace free-text profiles with atomic facts. Each fact must have one requested type, one paper, and at least one source ID.

```json
{
  "fact_id": "paper-a-dataset-001",
  "paper_id": "paper-a",
  "fact_type": "dataset",
  "value": "Google News corpus",
  "normalized_value": "google-news-corpus",
  "source_ids": ["paper-a-page-05-chunk-02"],
  "quote": "…",
  "page": 5,
  "section": "Experimental Setup",
  "extraction_status": "candidate",
  "type_validation": "pending",
  "ownership_validation": "pending"
}
```

Start with these fact types:

```text
research_question
hypothesis
assumption
method
baseline
dataset
population
sample_size
inclusion_criterion
exclusion_criterion
preprocessing
train_test_split
metric
result
uncertainty
statistical_test
limitation
future_work
```

### 6.3 Candidate findings

Every comparison result is a separate, auditable finding.

```json
{
  "finding_id": "cmp-001",
  "kind": "commonality",
  "dimension": "dataset",
  "statement": "Both papers evaluate on Dataset X.",
  "paper_ids": ["paper-a", "paper-b"],
  "fact_ids": ["paper-a-dataset-001", "paper-b-dataset-002"],
  "evidence_status": "directly_evidenced",
  "verification_status": "pending",
  "display_status": "candidate"
}
```

## 7. Ingestion and source-graph workflow

### 7.1 PDF validation

For every upload:

1. Detect whether the document is text-based or scanned.
2. Extract title, authors, year, DOI, and page count where possible.
3. Store the original PDF hash and parser version.
4. Identify headings before text flattening.
5. Flag low-quality extraction, missing pages, and OCR uncertainty.

### 7.2 Chunking

Create paragraph-aligned chunks around 500–1,000 tokens. Never merge unrelated pages merely to fill a chunk limit. Preserve page boundaries and detected section headings.

### 7.3 Tables and figures

1. Use deterministic table extraction first.
2. Preserve headers, units, labels, captions, and cell coordinates.
3. If extraction fails, render only that page and call `qwen3-vl:8b`.
4. Mark visual extraction as `candidate` until values can be reconciled with visible table content or user review.

## 8. Retrieval workflow

Embed every source artifact using `embeddinggemma:300m-qat-q4_0`.

Retrieval is performed separately for each task and each paper:

```text
Task: identify datasets
→ retrieve dataset/method/experiment chunks for Paper A
→ retrieve dataset/method/experiment chunks for Paper B

Task: compare limitations
→ retrieve limitation/conclusion/future-work chunks for each paper
```

Use section priors as a retrieval signal, but not as proof that a chunk answers a dimension. Fetch enough candidates for coverage, then let typed extraction return `not_found` if the paper does not support the fact.

## 9. Typed-fact extraction workflow

Run extraction per paper and per narrow fact type—not as one seven-field summary call.

Input:

```text
Requested fact type: DATASET
Paper identity: Paper A
Eligible source excerpts with IDs, pages, and sections
```

Output:

```json
{
  "facts": [
    {
      "value": "…",
      "source_id": "…",
      "quote": "…",
      "owner": "this_paper",
      "status": "candidate"
    }
  ],
  "not_found": false
}
```

Required extraction rules:

- Extract only explicit values in the supplied sources.
- Return `not_found: true` when evidence is missing.
- Do not classify a method as a dataset, a related-work mention as the paper's own setup, or a baseline as the proposed method.
- Keep one fact per atomic value.
- Require source IDs and a verbatim quote.

### Parser normalization

Build a single response normalizer before quality evaluation. It must accept:

- strings where objects were requested;
- singular/plural key variants;
- `items`, `findings`, `results`, and wrapper objects;
- top-level paper-label maps;
- nested or direct table cells;
- fenced JSON and harmless trailing commas.

Preserve raw model output even after normalization. Parser defects must be counted separately from model failures.

## 10. Fact validation workflow

Validation has three independent checks.

### 10.1 Provenance check

Confirm every source ID exists, belongs to the named paper, and includes the quoted excerpt.

### 10.2 Type check

Validate the requested entity type, such as dataset versus architecture, metric versus result, or limitation versus favorable property. Use source context and a narrow validation prompt:

```text
Requested type: DATASET
Candidate value: CBOW architecture
Source excerpt: …
Question: Is this the named dataset used by this paper? Return yes/no/uncertain and why.
```

The validator should return `uncertain` rather than force a positive answer.

### 10.3 Ownership and dimension check

Confirm the fact belongs to the current paper rather than related work, citation context, or a comparison paper. Also confirm that it answers the target dimension.

Facts that fail any check are excluded from deterministic comparison and retained only in an internal audit record.

## 11. Comparison workflow

### 11.1 Deterministic comparison first

Use code for comparisons that can be normalized:

| Dimension | Comparison method |
|---|---|
| Datasets | Normalized set intersection/difference |
| Populations | Structured attribute comparison |
| Sample sizes | Numeric comparison with units |
| Splits | Structured train/validation/test comparison |
| Methods/baselines | Normalized list comparison with source links |
| Metrics | Exact metric and direction comparison |
| Numerical results | Python computation after compatibility check |
| Statistical tests | Structured comparison of reported test and threshold |

### 11.2 Semantic comparison second

Use `qwen3:8b` only for dimensions that need interpretation: research question, assumptions, conceptual limitations, and possible contradictions.

The model receives only source-bound validated facts and their source excerpts. It may output one of:

```text
commonality_candidate
difference
direct_contradiction_candidate
apparent_contradiction
not_directly_comparable
insufficient_evidence
```

For a commonality, require evidence from every paper. For a direct contradiction, require comparable definitions, datasets, populations, and metrics. If any comparison condition differs, use `apparent_contradiction` or `not_directly_comparable`.

## 12. Numerical and table analysis

Build Python adapters to:

- normalize numeric cells, percentages, units, and metric direction;
- compare dataset sizes and class distributions;
- compare train/test splits;
- distinguish percentage change from percentage-point change;
- compute reported-score differences only when the metrics and evaluation conditions match;
- validate p-values, confidence intervals, standard deviations, and effect sizes where supplied;
- report inability to compare when required information is absent.

The LLM can explain the Python result but cannot create or alter computed values.

## 13. Claim-verification workflow

Do not use a generic profile reviewer as the authority.

For each candidate finding:

1. Gather only its exact supporting facts and primary excerpts.
2. Check that all cited papers have required evidence.
3. Run a narrow verifier over `statement + facts + source excerpts`.
4. Apply deterministic policy checks.
5. Set a user-facing status.

```text
DIRECTLY_EVIDENCED
NUMERICALLY_VERIFIED
EVIDENCE_BACKED_INTERPRETATION
PARTIALLY_SUPPORTED
INSUFFICIENT_EVIDENCE
UNSUPPORTED
```

Policy:

- `UNSUPPORTED` and `INSUFFICIENT_EVIDENCE` findings are not placed in the normal report body.
- `PARTIALLY_SUPPORTED` findings may appear only with that exact label and a limitation explanation.
- A second LLM pass may be a warning signal, but it is not independent proof.
- Never use cosine similarity as the final entailment or dimension-relevance gate.

## 14. Gap-analysis workflow

Generate candidate gaps only after facts and comparisons are validated.

Use these categories:

```text
population_gap
dataset_gap
method_gap
baseline_gap
metric_gap
theoretical_gap
reproducibility_gap
generalizability_gap
temporal_geographic_gap
ethical_fairness_gap
practical_deployment_gap
```

Every candidate gap requires evidence from each relevant paper:

```json
{
  "description": "Neither paper evaluates Population Z.",
  "category": "population_gap",
  "paper_a_evidence": ["paper-a-dataset-001"],
  "paper_b_evidence": ["paper-b-dataset-001"],
  "status": "candidate_gap",
  "coverage_note": "Based only on the selected papers"
}
```

If no valid gaps survive, return an explicit empty result with the reason rather than a silent empty list.

## 15. Novelty-candidate workflow

A pair of papers cannot establish novelty.

1. Build a local, authorized literature corpus: student uploads, university-licensed texts, abstracts, metadata, and citations.
2. Embed the corpus with EmbeddingGemma.
3. Retrieve 20–50 closest source artifacts for each candidate gap.
4. Compare the candidate gap against retrieved evidence.
5. Show corpus size, coverage dates, fields, and search limitations.

Allowed labels:

```text
novelty_not_assessed
possibly_novel_in_available_corpus
partially_addressed_in_retrieved_work
already_addressed_in_retrieved_work
insufficient_literature_coverage
```

Never output `proven novel`.

## 16. API and job design

Replace the synchronous 180-second compare request with background processing.

### Suggested endpoints

```text
POST /v1/spaces/{space_id}/compare-jobs
GET  /v1/compare-jobs/{job_id}
POST /v1/compare-jobs/{job_id}/cancel
GET  /v1/comparisons/{report_id}
POST /v1/papers/{paper_id}/evidence/rebuild
```

### Job phases

```text
queued
parsing
indexing
extracting_facts
validating_facts
comparing
computing_numerics
verifying_findings
identifying_candidate_gaps
checking_novelty_optional
rendering_report
completed | completed_with_warnings | failed | cancelled
```

Persist phase progress, partial failures, model metadata, and artifacts. The UI should say which result sections are still pending instead of timing out with a generic 504.

## 17. Database changes

Add or replace models approximately as follows:

```text
DocumentArtifact
  paper_id, source_id, kind, page, section, text/cells, hash, parser_version

EvidenceFact
  paper_id, fact_type, value, normalized_value, source_ids,
  quote, extraction_status, type_validation, ownership_validation,
  prompt_version, model_version

ComparisonFinding
  comparison_id, kind, dimension, statement, paper_ids, fact_ids,
  evidence_status, verification_status, display_status, reason

AnalysisJob
  id, state, progress, request parameters, model configuration,
  timestamps, error/warning details

LiteratureCorpusItem
  corpus_id, metadata, source/artifact references, permission provenance
```

Keep historical `ComparisonReport` records immutable, but mark profile-only reports as legacy and do not mix their confidence score with grounded reports.

## 18. UI changes

### Report layout

```text
Paper summaries
Evidence ledger
Deterministic comparison table
Commonalities
Differences and comparability conditions
Contradictions / apparent contradictions
Numerical and dataset analysis
Candidate gaps
Novelty assessment, if corpus search ran
Limitations and coverage
Evidence appendix
```

### Required UX behavior

- Every finding is clickable to its page, source excerpt, table, or figure.
- Display the evidence status beside every finding.
- Keep `Insufficient evidence` visible; do not replace it with empty invented cells.
- Explain whether a finding is direct evidence, a code-verified calculation, or an interpretation.
- Show extraction warnings, OCR uncertainty, missing sections, and corpus-coverage limits.
- Do not expose a single opaque confidence badge as the only quality signal.

## 19. Evaluation plan

Do not ship stronger claims based on model intuition alone. Build a faculty-reviewed test set before release.

### Test set design

Include paper pairs with:

- real agreement;
- genuine contradictions;
- apparent contradictions caused by different datasets or metrics;
- unrelated papers;
- tables and figures;
- scanned PDFs;
- missing limitations/datasets;
- related-work mentions likely to trigger ownership errors;
- architecture-versus-dataset and method-versus-metric traps.

### Measure separately

```text
Parser-shape success
Source-ID resolution
Quote fidelity
Fact-type precision/recall
Fact ownership precision/recall
Dimension relevance
Commonality precision
Contradiction precision
False cross-paper agreement rate
Numerical calculation accuracy
Gap precision
Appropriate abstention rate
Latency and memory by laptop tier
```

Do not merge parser failures, model failures, and source-extraction failures into one number.

### Release gate

Faculty reviewers should approve the evaluation set and define accepted thresholds. Until the system meets those thresholds, show candidate/interpretive labels rather than verified academic conclusions.

## 20. Implementation phases

### Phase 0 — Safety patch

1. Label current profile-only reports as legacy.
2. Stop calling profile-based findings `verified`.
3. Suppress unsupported findings from normal display.
4. Correct the UI timeout wording.
5. Add warnings when gap generation fails.
6. Pin model versions and preserve raw outputs.

### Phase 1 — Source foundation

1. Add page-aware document artifacts.
2. Repair heading-aware parsing and retain extraction-quality flags.
3. Add table/figure artifacts and rendered-page support.
4. Build retrieval index with EmbeddingGemma.
5. Add versioning and explicit rebuild/invalidation behavior.

### Phase 2 — Typed evidence extraction

1. Implement parser normalization.
2. Implement narrow fact extractors.
3. Implement provenance, type, ownership, and dimension validators.
4. Create the evidence-ledger UI.
5. Evaluate typed extraction before enabling semantic comparison.

### Phase 3 — Grounded comparison

1. Implement deterministic comparisons for data, metrics, baselines, and splits.
2. Add Python numerical checks.
3. Add source-limited semantic comparison.
4. Enforce both-paper evidence rules.
5. Add explicit apparent-contradiction and not-comparable outcomes.

### Phase 4 — Grounded gaps and report

1. Implement candidate-gap categories and policy checks.
2. Suppress unsupported findings.
3. Build page-linked report and evidence appendix.
4. Add job progress, cancellation, and partial-result warnings.

### Phase 5 — Literature and novelty

1. Add an authorized local literature corpus.
2. Implement corpus retrieval and coverage reporting.
3. Add conservative novelty-candidate labels.
4. Evaluate with faculty reviewers before release.

### Phase 6 — Deep-review tier

1. Add optional `qwen3:30b-thinking` / `qwen3-vl:32b-thinking` on university hardware.
2. Benchmark it against the student tier using the same evaluation set.
3. Publish capability and limitation differences in the UI.

## 21. Definition of done

The grounded Compare module is ready for student use only when:

- all displayed factual findings have clickable primary-paper evidence;
- profile text is not used as final evidence;
- every commonality has support from each named paper;
- incompatible numerical results are labeled not comparable;
- unsupported claims are withheld from the report body;
- no novelty claim is shown without corpus-coverage disclosure;
- parser and model failures are distinguishable in logs and evaluation;
- refresh rebuilds source-derived artifacts consistently;
- long-running work is a background job rather than a fragile synchronous request;
- faculty-reviewed evaluation demonstrates acceptable fact, comparison, and abstention quality.
