# Chat chunking experiment

**Completed pilot:** [results and recommendation](reports/pilot-20261002-v2/REPORT.md).
**Completed full-PDF follow-up:** [results, source coverage, and recommendation](reports/fullpdf-20261002-v2/REPORT.md).

## Full-PDF follow-up

The full-PDF follow-up uses six openly accessible originals: word2vec, Guppy,
GloVe, Quantum Programming Without the Quantum Physics, Tensor Quantum
Programming, and Preskill's NISQ paper. Official repository URLs and identity
checks are in [pdf_sources.json](pdf_sources.json). The NISQ paper replaces the
non-PDF web introduction; its question q19 is adapted accordingly. The other
23 questions, calibration splits, answer rubrics, and model settings are retained.
Reference expressions accept whitespace differences from fresh PDF extraction.

All **88 pages** have extractable text and are processed without page truncation,
abstract fallback, or silently skipped pages. Source hashes, per-page character
counts, detected headings/table/figure units and extraction flags are recorded.
This means complete **page coverage**, not lossless recovery of mathematical
notation, table associations or figure pixels. Seven table-extraction warnings
remain visible across word2vec, Guppy and Tensor; GloVe's labelled numeric table
has no such warning. No new OCR/vision descriptions are used.

Downloaded PDFs and extracts stay under ignored
`local\corpora\fullpdf-20261002`; they are never added to the Library or live index.
The earlier corpus and reports are not overwritten. Each new run freezes its own
corpus and question specification beneath `local\runs\<run>\inputs`.

From `research`:

```powershell
.\.venv\Scripts\python.exe -m chat_chunking.full_pdf
.\.venv\Scripts\python.exe -m chat_chunking.full_pdf_cases
.\.venv\Scripts\python.exe -m chat_chunking.benchmark validate `
  --corpus chat_chunking\local\corpora\fullpdf-20261002\corpus.json `
  --cases chat_chunking\local\corpora\fullpdf-20261002\case_spec.json
.\.venv\Scripts\python.exe -m chat_chunking.benchmark run `
  --run fullpdf-20261002-v2 `
  --corpus chat_chunking\local\corpora\fullpdf-20261002\corpus.json `
  --cases chat_chunking\local\corpora\fullpdf-20261002\case_spec.json
.\.venv\Scripts\python.exe -m chat_chunking.audits.reference_audit `
  --run fullpdf-20261002-v2
.\.venv\Scripts\python.exe -m chat_chunking.audits.full_pdf_analysis
.\.venv\Scripts\python.exe -m chat_chunking.audits.numeric_checks
```

Acquisition and case creation are write-once: if already complete, skip those two
commands. Model phases resume completed records only when code/input/model
checksums agree. For a repeat after a code change, choose a new run name rather
than rewriting a completed experiment. `--corpus` and `--cases` apply to preparation,
validation and `run`; later phases load the registered run's frozen inputs.

The first full-PDF preparation (`fullpdf-20261002`) was aborted before any answers:
a mathematical paragraph exceeded nomic-embed-text's 2,048 native-token context.
Semantic embedding now recursively bounds oversized paragraph units to 800
benchmark tokens, preserving all source offsets and text before grouping. The
fixed preparation is `fullpdf-20261002-v2`. No failed-preparation result is mixed
into its comparison; chunk size, parent retrieval, prompts and model controls
otherwise remain unchanged.

This is an isolated, first-pass RAG experiment, not a replacement Chat service.
It never imports backend/frontend code or writes the application's database,
indexes, configuration, papers, or chat history. Only a local Ollama server is
shared; running a benchmark can temporarily contend with interactive model use.

## Preregistered design

Four strategies, the same frozen sources, questions, embedding/answer/reviewer
models, retrieval recipe, and evidence budget:

1. **baseline**: 650 `cl100k_base` tokens with 81-token overlap (12.46%).
   Tail chunks may contain fewer than 500 tokens. Interior chunks are within the
   requested 500-800 range.
2. **research_aware**: section -> subsection -> paragraph packing, capped at 800
   tokens; source title, page, and detected heading metadata accompany each chunk.
3. **hierarchical_recursive**: section/subsection parents, recursively split
   children (paragraph -> sentence -> token boundaries), 320-token child target;
   retrieve children, return deduplicated parents capped at 800 tokens.
4. **hierarchical_semantic_structured**: hierarchical parent context, semantic
   paragraph grouping using the same embedding model, plus atomic table/figure
   units with their labels/captions. No new vision-generated descriptions; only
   locally saved figure evidence and deterministic extraction are available.

`cl100k_base` is a fixed **benchmark tokenizer**, not a claim that Ollama's Llama
or Gemma models use that tokenizer. Lengths and overlap are measured exactly with
this encoding; Ollama's actual prompt/output token counts are logged separately.
All strategies receive the same underlying text and extracted structures:
baseline treats them as flat text, while the advanced strategy preserves kinds.

Primary run: **24 questions x 4 strategies x 1 seed**. Eight questions are reserved
for threshold calibration and sixteen for held-out comparison. Questions and
source-grounded answer rubrics are frozen before model evaluation. No gold answers
or relevance labels are passed to retrieval, generation, or the peer reviewer.
These are agent-authored source checks, not independently human-adjudicated labels.

Controls: `nomic-embed-text:latest` embeddings, `llama3.2:3b` answers,
**`gemma4:latest` reviewer**, temperature 0, seed 42, top 8 contexts and a hard
2,400-token serialized evidence budget. Baseline is the requested experimental
baseline, not the application's existing 350-word chunker. This run measures
first-pass behavior, not the latency or final result of the live three-round loop.

Outcomes include chunk size/coverage, indexing time, retrieval relevance and
gold-evidence coverage, answer rubric coverage, citation validity, reviewer
support, exact quote provenance, claim-to-evidence similarity, correct
abstention, and answer/review latency. Retrieval/evaluation label granularity is
source-span based, not strategy-specific chunk IDs. Thresholds are swept on
calibration questions only and frozen before held-out scoring.

Model scores are not ground truth. A high similarity does not establish
entailment, and a model review alone cannot establish answer accuracy. Failures,
unanswerable cases, missing source structure, and incomplete runs remain in the
denominators and are reported rather than silently excluded.

## Setup

From the repository root:

```powershell
.\backend\.venv\Scripts\python.exe -m venv research\.venv
.\research\.venv\Scripts\python.exe -m pip install -r research\requirements.txt
Set-Location research
.\.venv\Scripts\python.exe -m chat_chunking.benchmark --help
```

Only install this experiment's dependencies into `research\.venv`, never the
backend environment. Raw local data and detailed answers live under ignored
`chat_chunking\local`; shareable aggregate reports live beside this document.
For the exact package versions of this pilot, install from
`research\requirements.lock.txt` instead of the ranged requirements.

## Reproduce or resume

From `research`, using the commands below:

```powershell
.\.venv\Scripts\python.exe -m pytest chat_chunking\tests -q
.\.venv\Scripts\python.exe -m chat_chunking.benchmark snapshot
.\.venv\Scripts\python.exe -m chat_chunking.benchmark validate
.\.venv\Scripts\python.exe -m chat_chunking.benchmark run --run reproduce-pinned-pilot
.\.venv\Scripts\python.exe -m chat_chunking.audits.reference_audit --run reproduce-pinned-pilot
```

The pinned-corpus snapshot is deliberately write-once. The existing corpus contains only pinned
paper evidence; it excludes users, passwords, chat conversations and production
embeddings. It uses a SQLite `mode=ro` connection and refuses an ambiguous
multi-owner corpus. Local PDF files are read, not modified. This pinned-source
snapshot does not download papers. Only the explicitly invoked full-PDF
acquisition command above downloads from the allowlisted public repositories;
neither mode invokes a vision model.

Individual resumable phases are `prepare`, `answer`, `similarity`, `review`, and
`report`. `prepare` warms models, freezes the model digests/configuration/code
checksum and question labels, builds each index, and records all retrievals.
`answer` generates every draft in a seeded shuffled strategy/question order.
`similarity` calculates citation-window cosine scores. `review` processes the
nonempty answers with Gemma 4; empty answers have no factual claims to review and
are evaluated as abstentions. `report` refuses to present an incomplete run as a
completed comparison. Reusing a run after changing experiment code, corpus, model
digests, questions or settings is rejected.

The phases are separated to reduce model swapping on local hardware. Per-call
latency is still wall-clock and includes any load/queue time; Ollama load times
are recorded separately. The reported answer+review path is **not** live
end-to-end chat latency (query embedding, separate evidence-window embedding,
rewriting, persistence, and multiple review rounds are not included in that sum).
Embedding cache hits/misses are reported: timings are not pure cold-index costs.

Outputs:

- `local\corpus.json`: immutable, checksummed canonical source text.
- `local\runs\<run>\manifest.json`: exact controls, software/model identity,
  source limits and hashes.
- `local\runs\<run>\inputs`: frozen corpus and case specifications for new runs.
- `local\runs\<run>\indexes`: chunks, hierarchy and NumPy vectors.
- `local\runs\<run>\retrieval`, `answers`, `similarities`, `results`: per-case
  source spans, generated claims, metrics and errors.
- `local\runs\<run>\calls`: original local-model responses, timing and token use.
- `reports\<run>\summary.json` and `per_question.csv`: shareable aggregate and
  per-question metrics, without paper excerpts or generated answer text.

## Interpreting the metrics

- **Evidence recall**: fraction of preregistered supporting-span groups fully
  covered by the selected contexts. Repeated occurrences of a labelled passage
  are accepted as alternatives. A valid but unlabelled alternative can be missed.
- **MRR / context precision**: ranking and proportion of selected contexts that
  overlap any labelled span; this is sparse relevance annotation, not exhaustive
  expert relevance assessment of the entire paper.
- **Rubric coverage / full match**: predefined answer concepts and forbidden
  numerical confusions checked without consulting the peer review. These are
  transparent lexical proxies, not an assertion of human-certified accuracy.
- **Reference-supported answer**: full rubric match, valid citations, and all
  gold evidence groups covered by the cited contexts. Extra incorrect assertions
  still require claim review; this proxy does not prove every assertion.
- **Claim support**: Gemma 4's SUPPORTED findings divided by all generated claims.
  Review failures do not get counted as supported claims.
- **Correct abstention** is contract-level: an unanswerable question must return
  an empty claims array. Verbal statements that information is absent, emitted as
  cited factual claims instead, are not credited by this metric. Inspect the raw
  answer before interpreting a failure here as a fabricated positive assertion.
- **Quote provenance**: the reviewer's quotation must occur in a cited passage
  after case/whitespace normalization; this tests provenance, not entailment.
- **Evidence similarity**: minimum over a claim's cited chunks of its best
  160-token recursive excerpt cosine. This is not the application's 500-character
  windowing implementation; its numerical thresholds need separate production
  validation before adoption.
- **Strict acceptance** requires APPROVED, every claim supported, valid IDs, exact
  quote provenance, and both review-score and cosine thresholds. The reference
  pair is 0.90/0.65. Calibration sweeps review 0.80/0.85/0.90/0.95 against cosine
  0.50-0.80 in 0.05 steps, selecting maximum coverage with no *proxy* false accepts
  and at least three accepted calibration cases. If that criterion is not met,
  the reference thresholds are retained and explicitly not called calibrated.

No test-set threshold tuning or production promotion is performed. A one-seed,
small-corpus pilot supports a direction for further experiments, not a universal
winner or a precise throughput capacity estimate.

The initial `pilot-20261002` run was stopped for an input-integrity correction:
PDF table extraction had merged multiple numeric rows into multiline cells.
The replacement `pilot-20261002-v2` expands those rows only when column line
counts match, flags ambiguous tables, and reruns all four strategies. The
q04 reference recognizes both equivalent plain-text and pipe-separated
serializations of the same 75.0-percent result. No answers from the stopped
run are mixed into the replacement run or used in its summary.

The optional reference-aware audit is a separate, post-hoc Gemma 4 assessment of
factual content and completeness against source references. It is blind to the
strategy name and lexical regex rubric. It does not regenerate answers, alter the
primary report, or tune thresholds. Its own code/model fingerprints and raw
responses are retained, and its latency is excluded from the primary timings.
The full-PDF follow-up confirmed numeric false positives in this model audit.
Its raw scores are therefore labelled judge proxies, not proven accuracy.
`audits.numeric_checks` independently checks the explicit q04 table value without
modifying primary results or recalibrating thresholds.
