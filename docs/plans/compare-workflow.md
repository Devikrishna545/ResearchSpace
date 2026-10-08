# Compare Module – Grounded Workflow

This document describes how the Compare feature works now. It implements
[grounded_compare_implementation_plan.md](../grounded_compare_implementation_plan.md),
motivated by the measurements in
[DECISION.md](../backend/evaluations/compare/DECISION.md). The former
profile-only compare (`CompareAgent`, `GapAgent`, `ProfileStore`, and
`POST /v1/spaces/{id}/compare`) has been removed. Its old report rows stay in
the database untouched, but they are hidden: the list omits them and opening
one returns HTTP 410.

## Rules the code enforces

1. A generated profile is never evidence. Findings cite page-aware source
   artifacts parsed from the paper itself.
2. Every shown factual finding resolves to a source span, page and paper
   (the report's evidence appendix).
3. A commonality needs validated facts from **every** paper it names. A direct
   contradiction also needs comparable conditions, meaning a shared dataset or
   population; otherwise it is downgraded to an *apparent contradiction*.
4. Unsupported and insufficient findings are withheld from the report body.
   Empty cells say "Insufficient evidence".
5. Numbers are compared in Python (`numerics.py`), never by the model.
6. Novelty is only assessed against an authorized corpus, with a coverage
   disclosure. The system never says "proven novel".
7. Embedding similarity only ranks retrieval candidates. It never gates
   support, entity type or dimension relevance.

## Models (pinned tags)

Settings live in [config.py](../backend/app/core/config.py). Tiers are defined in
[tiers.py](../backend/app/modules/compare/grounded/tiers.py).

| Tier | Text | Vision | Retrieval | Notes |
|---|---|---|---|---|
| `student` (default) | `qwen3:8b` | `qwen3-vl:8b-instruct` | `embeddinggemma:300m-qat-q4_0` | Typed extraction, validation, candidate comparison |
| `weak` | `qwen3:4b` | `qwen3-vl:4b-instruct` | same | Candidates only; interpretive findings are always shown with a caveat |
| `deep` | `qwen3:30b-thinking` | `qwen3-vl:32b-thinking` | same | Optional university hardware; same evidence rules |

Every call uses temperature 0, a fixed seed (`GROUNDED_SEED`, default 42),
and an Ollama JSON schema. The vision model is the non-thinking `-instruct` variant: the
thinking `qwen3-vl:8b` tag ignores `think=false` and spent its whole token budget
reasoning without answering in a local test. Each report records the Ollama version, the model
digests, prompt versions, parser version and seed. Chat and search keep
`nomic-embed-text`. The EmbeddingGemma vectors live only in
`document_artifacts`, the Compare evidence index.

## End-to-end flow

```
UI: ComparePanel ── POST /v1/spaces/{id}/compare-jobs {paper_ids, refresh, check_novelty, tier}
                     → 202 + job; UI polls GET /v1/compare-jobs/{job_id}; POST …/cancel stops it
Background job (app/modules/compare/grounded/jobs.py), one at a time per process:
 parsing            EvidenceBuilder: local upload → publisher PDF → ingest chunks → abstract
                    pdfplumber text/tables/captions, heading-aware paragraph chunks (500–1,000 tokens,
                    never across pages), scanned pages / uncaptured tables / figures → qwen3-vl on the
                    rendered page only (candidate status)
 indexing           EmbeddingGemma vectors per artifact
 extracting_facts   per paper × per fact type: retrieval (similarity + section priors) → narrow extraction
 validating_facts   provenance (code: source ID, quote, value in source), type (LLM), ownership + dimension (LLM)
 comparing          deterministic entity comparison over validated facts; semantic comparison of
                    research question / assumptions / methods / limitations / future work
 computing_numerics sample sizes, splits, results (same metric + dataset + split), statistical checks
 verifying_findings narrow per-finding verifier + policy → evidence status and display status
 identifying_candidate_gaps  gaps citing validated facts from each relevant paper, then verified
 checking_novelty_optional   corpus retrieval (top 20–50) + conservative labels + coverage
 rendering_report   immutable report snapshot + comparison_findings rows
```

Evidence builds and facts persist per paper version. A later job reuses them.
It also reuses the whole report when the builds, models and prompts are
unchanged, so an interrupted job resumes cheaply when re-run.

## Fact types and validation

Fact types are defined in [fact_types.py](../backend/app/modules/compare/grounded/fact_types.py):
research question, hypothesis, assumption, method, baseline, dataset,
population, sample size, inclusion/exclusion criteria, preprocessing,
train/test split, metric, result, uncertainty, statistical test, limitation and
future work.

A fact is **validated** only when all four checks pass:

| Check | How | Fails when |
|---|---|---|
| Provenance | code (`validation.py`) | the source ID is unknown or belongs to another paper, the quote is not in the source (fuzzy ≥ 0.92 allowed), or the value is not in the source |
| Type | narrow LLM check | e.g. "CBOW architecture" offered as a dataset |
| Ownership | LLM check + rule | the value belongs to cited/related work; any fact sourced from a Related Work section fails |
| Dimension | LLM check | the quote only mentions the dimension instead of stating it |

The validators answer `uncertain` rather than forcing a pass. Uncertain and
rejected facts stay in the report's audit record and are never compared.

## Parser normalization

[normalizer.py](../backend/app/modules/compare/grounded/normalizer.py) is used by every call.
It accepts strings where objects were requested, singular/plural keys, the
`items`/`findings`/`results` wrappers, top-level `P1`/`P2` label maps,
nested or direct table cells, fenced JSON, `<think>` blocks and trailing
commas. Each raw output is stored in `llm_call_logs` with a `parse_status`.
`parser_defect` means valid JSON that the code could not map, which is our
bug. `model_invalid_json`, `model_empty` and `model_error` are model failures.
`GET /v1/compare-jobs/{id}/diagnostics` reports them separately.

## Evidence statuses in the UI

| Status | Meaning | Shown |
|---|---|---|
| `DIRECTLY_EVIDENCED` | stated in the cited spans of every named paper | yes |
| `NUMERICALLY_VERIFIED` | computed or checked in Python | yes |
| `EVIDENCE_BACKED_INTERPRETATION` | interpretation the verifier found supported | yes |
| `PARTIALLY_SUPPORTED` | part supported | yes, with a caveat |
| `INSUFFICIENT_EVIDENCE` / `UNSUPPORTED` | — | withheld (listed under limitations) |

## API

| Method | Path | Purpose |
|---|---|---|
| POST | `/v1/spaces/{space_id}/compare-jobs` | Start a grounded compare job |
| GET | `/v1/spaces/{space_id}/compare-jobs` | Recent jobs (used to resume after reload) |
| GET | `/v1/compare-jobs/{job_id}` | Phase, progress, pending sections, warnings |
| POST | `/v1/compare-jobs/{job_id}/cancel` | Cancel |
| GET | `/v1/compare-jobs/{job_id}/diagnostics` | Parser vs model failure counts |
| GET | `/v1/spaces/{space_id}/comparisons` | Grounded report summaries |
| GET | `/v1/comparisons/{report_id}` | Grounded report (410 for retired profile-only reports) |
| POST | `/v1/papers/{paper_id}/evidence/rebuild` | Rebuild a paper's evidence; older reports are flagged stale |
| GET | `/v1/papers/{paper_id}/evidence` | Evidence ledger and audit record |
| GET | `/v1/evidence/artifacts/{artifact_id}[/image]` | Source span / rendered page |
| GET, POST, DELETE | `/v1/corpus`, `/v1/corpus/papers`, `/v1/corpus/items[/{id}]` | Authorized literature corpus |
| GET | `/v1/grounded/tiers` | Tier capabilities and limitations |

## Storage (migration `0008_grounded_compare`)

`paper_evidence_builds`, `document_artifacts`, `evidence_facts`,
`llm_call_logs`, `analysis_jobs`, `comparison_findings`,
`literature_corpus_items`. In addition, `comparison_reports` gains
`report_kind`, `report_json` and `job_id`.

## Evaluation

See [evaluations/compare/grounded/README.md](../backend/evaluations/compare/grounded/README.md).
Until faculty approve a gold set and set the thresholds, the release gate
cannot pass. Reports carry a banner saying findings are candidates or
interpretations, not verified academic conclusions.
