# Chat chunking experiment: measured results

**Date:** 2026-10-02  
**Status:** Completed isolated pilot; no application changes or automatic promotion.  
**Run:** `pilot-20261002-v2`  
**Reviewer:** `gemma4:latest`, digest
`dc35e8d9c6061baa6f0fa870975ab6932e2542b579b13ea0f199fa4bb7300c9c`

## Decision

**Hierarchical + recursive chunking is the most promising next candidate, not a
proven production winner.** It improved labelled evidence recall and claim support
over the experimental baseline while tying its reference-aware answer accuracy.
However, the retrieval gain on held-out questions is only one additional
answerable question, the index is larger, and strict citation acceptance is still
low. The intervals are too wide to establish superiority.

The **650-token overlapping baseline remains a strong low-cost comparator**.
Research-aware chunking improved the initial keyword-based rubric score, but that
advantage disappeared in the separate reference-aware audit. The
semantic/table/figure-aware implementation achieved the best ranking MRR but did
not turn that into better answers or claim support.

**Do not switch the live Chat implementation or lower its thresholds on these
results alone.** The live 350-word chunker was not a fifth experimental arm, so this
study does not demonstrate that any candidate beats the current application.

## 1. What ran

- Four strategies, **24 fixed questions each, one seeded generation each**:
  **96 answer attempts**, all completed without recorded execution errors.
- **297 generated claims** and **434 citations** evaluated in the primary run.
- Eight calibration questions and sixteen held-out questions. The latter contain
  fourteen answerable and two unanswerable questions.
- Six pinned documents, approximately **54,044 benchmark tokens** in total.
  One original local PDF (GloVe); five reconstructed saved-text sources, including
  a web capture and an abstract-only paper. Only the local PDF supported direct
  paragraph/layout/table extraction. All strategies used the same canonical text.
- `nomic-embed-text:latest` embeddings, `llama3.2:3b` answer generation,
  **`gemma4:latest` peer review**, Ollama 0.35.0.
- Temperature 0, seed 42, 8,192 model context setting, up to eight retrieved
  contexts, hard **2,400-token serialized evidence budget**.
- Same hybrid retrieval recipe across arms: cosine + TF-IDF-like sparse search,
  reciprocal-rank fusion, heuristic reranking, MMR-style diversification.
- First-pass answering and review, **not** the live three-round refinement loop.

### Strategies

| Strategy | Definition |
|---|---|
| Baseline | 650 `cl100k_base` tokens, 81-token overlap (12.46%); shorter document tails allowed |
| Research-aware | Section -> subsection -> paragraph packing; source/page/heading metadata; maximum 800 tokens |
| Hierarchical + recursive | Section/subsection parents up to 800 tokens; recursively split children up to 320 tokens; retrieve children, return deduplicated parents |
| Hierarchical + semantic + structured | Semantic paragraph grouping, hierarchical parents/children, atomic table/caption/figure-text handling; no new vision inference |

The tokenizer is a fixed benchmark tokenizer, **not** Ollama's actual Llama/Gemma
tokenizer. Ollama prompt/output counts are separately retained. Figure awareness
here means caption/text structure, not interpreting unseen image pixels.

## 2. Main held-out comparison

Evidence recall and answer accuracy below use **14 answerable held-out questions**.
Claim support uses all generated claims across the **16 held-out attempts**.

| Strategy | Labelled evidence recall | Reference-aware correct + complete answers* | Peer-reviewed claim support | Median answer/review path** |
|---|---:|---:|---:|---:|
| Baseline | 64.3% (9/14) | 64.3% (9/14) | 77.6% (38/49) | 6.28 s |
| Research-aware | 64.3% (9/14) | 64.3% (9/14) | 68.0% (34/50) | 6.21 s |
| Hierarchical + recursive | **71.4% (10/14)** | 64.3% (9/14) | **80.4% (45/56)** | 6.74 s |
| Hierarchical + semantic + structured | **71.4% (10/14)** | 57.1% (8/14) | 63.6% (35/55) | 6.83 s |

\* A **post-hoc, strategy-blind Gemma 4 audit** against reference passages and the
exact question. This is a model-judged accuracy proxy, not independent human ground
truth. It grades factual content/completeness separately from citation correctness.
Its inputs and outputs are saved separately, and it did not change primary metrics
or threshold selection.

\** Median of ranking + answer generation + peer-review wall time. It excludes
query rewriting, shared query embedding, the separate citation-window embedding
phase, database persistence, and additional refinement iterations. It includes any
model-call load/queue time. It is **not live end-to-end Chat latency or a load test**.
Supplemental reference-audit time is not included.

Held-out MRR was **0.488 / 0.560 / 0.577 / 0.619**, respectively. Semantic/structured
retrieval ranked labelled evidence best, but answer generation and citation
selection remained bottlenecks.

### Why the original rubric is not called "accuracy"

The preregistered lexical full-rubric matches were:

| Strategy | Held-out lexical full match | All-20-answerable lexical full match | All-20-answerable reference-aware accuracy proxy |
|---|---:|---:|---:|
| Baseline | 64.3% | 60.0% | 65.0% |
| Research-aware | 78.6% | 75.0% | 75.0% |
| Hierarchical + recursive | 71.4% | 70.0% | 70.0% |
| Hierarchical + semantic + structured | 64.3% | 70.0% | 65.0% |

Spot checks found real false negatives. For example, a correct Figure 4 answer
gave the corpus, vector dimension and window size but did not satisfy a rigid
keyword-distance/extra-detail rubric. Similarly, a concise answer naming classical
data types did not include every background concept in its rubric. These are
reasons to retain the transparent primary scores **and** run a separate semantic
audit, not to silently rewrite labels after seeing results.

## 3. Claim, citation and threshold findings

**100% of citation IDs existed in the supplied contexts. That did not mean the
citations supported the claims.** The structured output schema restricts IDs; it
cannot make the model choose the right passage.

The strict gate requires:

1. APPROVED and reviewer score at or above the threshold;
2. every claim SUPPORTED;
3. valid cited IDs;
4. every review quote present in a cited passage after case/whitespace normalization;
5. each claim's minimum cited-passage similarity at or above the evidence threshold.

Reference thresholds were **review >= 0.90 and similarity >= 0.65**.

| Strategy | Held-out answers passing the strict reference gate | Reference-aware audit of accepted answers |
|---|---:|---:|
| Baseline | 4/16 | 4/4 judged correct and complete |
| Research-aware | 0/16 | No accepted answers |
| Hierarchical + recursive | 3/16 | 3/3 judged correct and complete |
| Hierarchical + semantic + structured | 1/16 | 1/1 judged correct and complete |

Eight accepted answers across all arms are far too few to assert calibrated
precision. The original strict reference-span/rubric proxy counted fewer of these
as successful; the separate audit identified several proxy false negatives.

### Calibration, not test-set tuning

Twenty-eight pairs were swept on the **32 calibration attempts only**:
review scores 0.80, 0.85, 0.90 and 0.95; cosine 0.50 through 0.80 in 0.05 steps.

- At cosine 0.50/0.55, five calibration answers passed; four satisfied the original
  strict reference/rubric proxy.
- At cosine 0.65, two passed; one satisfied that proxy.
- No pair met the preregistered rule of zero proxy false acceptances with at least
  three accepted cases.
- The code therefore retained **0.90/0.65 as reference settings, not as a newly
  optimized recommendation**.
- Reviewer thresholds from 0.80 to 0.95 made no difference to acceptance in this
  sample because the other gates and coarse score distribution dominated.
- The supplemental audit was **not used to retune thresholds**, especially not on
  held-out answers.

These similarities use 160-token recursive excerpts, whereas the live Chat
grounding code uses different character windows. The numerical threshold must not
be transferred as though those measurements were interchangeable.

### Unanswerable questions

All four strategies failed the strict empty-claims abstention contract (0/4 each).
That does not mean every response invented a positive answer: some verbally said
the requested information was unavailable, but still emitted cited claims.

The separate audit credited honest semantic abstentions on 1/4 cases for baseline,
research-aware and hierarchical-recursive, and 2/4 for semantic/structured.
**None of the sixteen unanswerable primary attempts passed the strict gate.**

## 4. Concrete failure modes

- **Correct evidence, wrong number:** research-aware retrieval included the correct
  GloVe table row, but generation answered 75.9% instead of 75.0%. The peer reviewer
  flagged it. Chunking alone did not fix the numerical reasoning/selection error.
- **Correct answer, wrong citation:** semantic/structured generation gave 75.0%,
  but cited other supplied passages instead of the table row. The reviewer withheld
  support despite a reference-aware factual match.
- **Unlabelled alternatives and concise answers:** strict span/rubric scoring can
  reject an otherwise correct response; do not confuse proxy failure with proof
  that the underlying statement is false.
- **Figure-query retrieval:** the weighting-function question still missed its
  labelled evidence in all four arms. Better document/entity-aware ranking is a
  separate issue from chunk boundaries.

## 5. Storage and build cost

| Strategy | Indexed child units | Parent units | Vector array size | Observed build + indexing |
|---|---:|---:|---:|---:|
| Baseline | 97 | 0 | 0.568 MiB | 8.93 s |
| Research-aware | 155 | 0 | 0.908 MiB | 7.37 s |
| Hierarchical + recursive | 290 | 155 | 1.699 MiB | 15.81 s |
| Hierarchical + semantic + structured | 328 | 202 | 1.922 MiB | 22.82 s |

These are this harness's float64 vector arrays, not the total SQLite/JSON footprint.
The embedding cache was shared within the run: research-aware and semantic
strategies reused some text vectors. Consequently, **these times are not unbiased
cold-index comparisons**. Cache hit/miss counts and semantic embedding time are in
the machine-readable report. The semantic arm spent about 19.32 s in paragraph
embedding during construction.

All strategies stayed within the 2,400-token serialized context cap. Structured
strategies can create very short heading/tail units; their size distributions are
included in the report rather than hidden by reporting only averages.

## 6. Confidence and limits

- One generation seed, one local machine, six related documents; not a throughput,
  concurrency, or multi-turn follow-up benchmark.
- Only one original PDF. Section/paragraph recovery on the other documents is
  limited by text already flattened during ingestion. No claim of full multimodal
  coverage or universally superior semantic chunking is justified.
- Reference labels are source-grounded but agent-authored, not independently
  human-adjudicated. The peer reviewer and semantic auditor share the same model,
  so their errors can be correlated.
- Paired question bootstrap, 10,000 resamples, seed 42: hierarchical-recursive's
  held-out evidence-recall difference versus baseline is **+7.1 percentage points**
  with an exploratory 95% interval of **-14.3 to +28.6 points**.
  Its audited answer-accuracy difference is **0 points**, interval **-35.7 to
  +35.7 points**. These are small-sample exploratory intervals, not adjusted for
  multiple comparisons.
- An initial run was stopped after detecting multiline table cells with ambiguous
  row association. The shared parser was corrected, and **every arm was rerun**.
  The invalidated pilot's raw records remain local for audit and are excluded here.

## 7. Next experiment before promotion

1. Obtain original PDFs for a larger, more varied, permissioned corpus.
2. Add the application's current 350-word/50-word-overlap chunker as a fifth control.
3. Repeat at least three seeds; use independently reviewed reference answers.
4. Focus on **hierarchical-recursive vs baseline**, with research-aware as a
   lower-complexity structured comparator.
5. Test citation selection, numerical/table binding, and explicit abstention
   independently before increasing chunker complexity.
6. Re-evaluate the actual Chat refinement loop and its own citation-window
   thresholds, including cold/warm latency and concurrent usage.

## Reproduce and inspect

- [Experiment instructions and commands](../../README.md)
- [Primary metrics and full manifest](summary.json)
- [Per-question metrics](per_question.csv)
- [Separate reference-aware audit](reference_audit.json)
- [Exploratory uncertainty estimates](uncertainty.json)
- Local, ignored detailed evidence/answers:
  `research\chat_chunking\local\runs\pilot-20261002-v2`

Validation: **16 isolated tests passed**, all 24 reference cases bound to saved
evidence, 96 unique strategy/question results present, model digests and input
checksums verified. Git inspection shows changes only under `research`.
