# Chat chunking: full-PDF follow-up

**Date:** 2026-10-02  
**Run:** `fullpdf-20261002-v2`  
**Status:** Completed, isolated research experiment. No live application changes.

## Executive conclusion

Full PDFs improved several answer outcomes, but **missing full text was not the
only limitation**. Correct source passages still led to incorrect numbers,
wrong citations, unsupported extra claims, and model-review errors.

The new run changes the practical shortlist:

- **Baseline** had the highest *model-judged* held-out answer score and the
  smallest index.
- **Research-aware** had the highest held-out peer-reviewed claim support,
  the fastest median measured answer/review path, and a smaller index than the
  hierarchical variants. It is the strongest structured candidate to test next.
- **Hierarchical + semantic + table/figure-aware** retrieved the most labelled
  evidence, but did not convert that into the highest answer score.
- **Hierarchical + recursive**, the promising candidate from the first pilot,
  did not establish an answer-quality advantage on the full-PDF corpus.

**Next comparison: baseline versus research-aware**, with repeated seeds and
independent reference checks. Do not automatically promote a chunker or loosen
thresholds. This remains a small pilot, not a demonstration that either arm
outperforms the application's current 350-word chunker.

## 1. Full-PDF corpus and extraction

| Original paper | Official source | Pages processed | Benchmark tokens | Text blocks | Table units | Figure/caption units |
|---|---|---:|---:|---:|---:|---:|
| Efficient Estimation of Word Representations in Vector Space | [arXiv v3](https://arxiv.org/abs/1301.3781v3) | 12/12 | 10,512 | 95 | 9 | 1 |
| GUPPY: Pythonic Quantum-Classical Programming | [arXiv v1](https://arxiv.org/abs/2510.12582v1) | 7/7 | 5,621 | 45 | 0 | 2 |
| GloVe: Global Vectors for Word Representation | [ACL Anthology](https://aclanthology.org/D14-1162/) | 12/12 | 12,956 | 118 | 6 | 5 |
| Quantum Programming Without the Quantum Physics | [arXiv v2](https://arxiv.org/abs/2408.16234v2) | 20/20 | 14,075 | 151 | 0 | 2 |
| Tensor Quantum Programming | [arXiv](https://arxiv.org/abs/2403.13486) | 17/17 | 21,169 | 182 | 0 | 3 |
| Quantum Computing in the NISQ era and beyond | [arXiv](https://arxiv.org/abs/1801.00862) | 20/20 | 15,475 | 168 | 0 | 0 |
| **Total** | | **88/88** | **79,808** | **759** | **15** | **13** |

Five originals correspond to research works used in the previous pilot.
Preskill's paper replaces the non-PDF web introduction, so **q19 is adapted**.
The other 23 questions, answer rubrics and calibration/held-out assignments are
unchanged. Reference regexes accept fresh extraction's whitespace differences.

Every download passed PDF-content, page-count, SHA-256 and first-page identity
checks. Both PDF readers agreed on the page count; all pages contained extractable
digital text. **No abstract fallback, skipped pages or page truncation** occurred.
All four indexes cover every one of the **787 canonical source blocks**.

Complete page coverage is **not** lossless interpretation:

- Seven ambiguous-table extraction warnings occur on five distinct pages across
  word2vec, Guppy and Tensor. The warnings are retained in the audit; table units
  are heuristic detections, not human-certified reconstructed tables.
- GloVe's labelled numerical table has no such row-alignment warning.
- Figures are represented by extractable text/captions, not visual interpretation
  of their pixels. Equations and PDF reading order may still be imperfect.
- No OCR or vision model was invoked. There is no claim of full multimodal
  extraction accuracy.

See [extraction_audit.json](extraction_audit.json) for exact source hashes,
download sizes, identities and per-page coverage.

## 2. Experimental controls

Same four strategies and numerical settings as the earlier pilot:

1. **Baseline:** 650 benchmark tokens, 81-token overlap (12.46%), shorter tails.
2. **Research-aware:** section -> subsection -> paragraph, maximum 800 tokens.
3. **Hierarchical + recursive:** parents up to 800 tokens, children up to 320;
   retrieve children and return deduplicated parent context.
4. **Hierarchical + semantic + structured:** semantic grouping and atomic
   table/figure-text units, with the same parent/child limits.

Same `cl100k_base` length measurement, hybrid ranking, top-eight contexts and hard
2,400-token serialized evidence cap. Temperature 0, seed42, model context8,192.
No gold labels or reference answers are passed to retrieval, generation or peer
review. First-pass generation/review, not the live multi-round Chat loop.

| Role | Exact tag | Digest |
|---|---|---|
| Answer | `llama3.2:3b` | `a80c4f17acd55265feec403c7aef86be0c25983ab279d83f3bcd3abbcb5b8b72` |
| Embedding | `nomic-embed-text:latest` | `0a109f422b47e3a30ba2b10eca18548e944e8a23073ee3f3e947efcf3c45e59f` |
| Reviewer and separate reference audit | **`gemma4:latest`** | `dc35e8d9c6061baa6f0fa870975ab6932e2542b579b13ea0f199fa4bb7300c9c` |

All model digests match the previous pilot.

The first preparation attempt failed before generating any answers because a
long mathematical paragraph exceeded nomic-embed-text's2,048 native-token input
limit. Rather than truncate, the semantic preprocessing now recursively bounds
oversized embedding units to800 benchmark tokens, preserving all source offsets.
A coverage regression test verifies this. The failed preparation is archived and
excluded; the fixed run rebuilt all four indexes.

## 3. Held-out results

Twenty-four questions per strategy: eight calibration, sixteen held-out.
The held-out set contains fourteen answerable and two unanswerable questions.

| Strategy | Labelled evidence recall* | Reference-audit answer score** | Peer-reviewed claim support*** | Median answer/review path**** |
|---|---:|---:|---:|---:|
| Baseline | 71.4% | **85.7% (12/14)** | 60.0% (30/50) | 5.99s |
| Research-aware | 71.4% | 78.6% (11/14) | **82.5% (33/40)** | **4.55s** |
| Hierarchical + recursive | 75.0% | 64.3% (9/14) | 81.4% (48/59) | 7.16s |
| Hierarchical + semantic + structured | **78.6%** | 71.4% (10/14) | 76.2% (32/42) | 5.88s |

\* Mean supporting-span-group coverage across14 answerable questions.
Cross-paper questions have multiple evidence groups, so75% is not an integer
number of fully answered questions.

\** A separate, strategy-blind Gemma4 judgement against source references.
**This is an accuracy proxy, not independently established accuracy. Confirmed
judge false positives are documented below.** Factual answer content is scored
separately from citation support.

\*** All generated claims in16 held-out attempts, including unanswerable cases.
The baseline review failure contributes no supported claims. For **answerable
questions alone**, the support rates are68.2% baseline,84.2% research-aware,
82.1% hierarchical-recursive and80.0% semantic/structured. This sensitivity view
does not replace the primary all-attempt denominator.

\**** Ranking + generation + peer-review wall time. Excludes separate
query/citation embedding phases, rewriting, persistence, repeated refinement,
and the supplemental accuracy audit. Includes model load/queue time and the
failed review. Not live end-to-end Chat latency or concurrency throughput.

Held-out MRR:0.607 baseline,0.465 research-aware,0.512 hierarchical-recursive,
0.538 semantic/structured. Retrieval recall alone does not determine answer
quality or correct citation selection.

### Execution outcomes

- **96/96 primary records**,283 generated claims and480 citations.
- **95 primary evaluations without recorded execution errors**; one baseline
  review for unanswerable q22 hit the unchanged1,600-output-token cap. It was
  retained as a failure, not selectively retried or dropped.
- **96/96 separate reference audits**, no recorded execution errors.
- All supplied citation IDs were valid; valid IDs do not prove entailment.

## 4. Did full PDFs fix the earlier limitation?

For the cleaner comparison below, **q19 is excluded**, leaving13 unchanged
answerable held-out questions. Each cell is the separate reference-audit score.

| Strategy | Saved-text pilot | Full-PDF follow-up | Difference |
|---|---:|---:|---:|
| Baseline | 69.2% (9/13) | 84.6% (11/13) | +15.4 percentage points |
| Research-aware | 69.2% (9/13) | 76.9% (10/13) | +7.7 points |
| Hierarchical + recursive | 61.5% (8/13) | 69.2% (9/13) | +7.7 points |
| Hierarchical + semantic + structured | 53.8% (7/13) | 69.2% (9/13) | +15.4 points |

On these same13 questions, labelled evidence recall was unchanged at69.2% for
baseline and research-aware, increased69.2% ->73.1% for recursive, and
69.2% ->76.9% for semantic/structured.

**Interpretation:** fresh full text helped some measured outcomes, but it did not
universally improve retrieval or make the advanced strategies best at answering.
The corpus grew from approximately54k to80k benchmark tokens, and one document
was replaced. Although common-question comparison removes q19's direct scoring
change, it does not remove changed retrieval competition. These are not pure
causal estimates of extraction quality alone.

Small-sample uncertainty remains large. For example, baseline's +15.4-point
common-question answer-score change has an exploratory paired-question95%
bootstrap interval of **-23.1 to +53.8 points**. Research-aware versus baseline
on the new14-answerable set differs by-7.1 points, interval-28.6 to+14.3.
These use10,000 question-paired resamples, one generation seed, and no
multiple-comparison adjustment. See [paired_analysis.json](paired_analysis.json).

## 5. Thresholds and remaining evidence problems

The same28 reviewer-score/cosine pairs were swept on the32 calibration
attempts only. No held-out threshold tuning.

- The preregistered criterion was maximum coverage with zero
  reference/rubric-proxy false acceptances and at least three accepted cases.
- **No threshold pair met that criterion.**
- Reference settings remain **review score >=0.90; evidence similarity >=0.65**.
  They are not claimed to be newly optimized.
- At review0.80/cosine0.50, five calibration attempts passed; three satisfied
  the strict reference/rubric proxy. At cosine0.65, four passed; two satisfied
  it. Lowering the threshold would not demonstrate safe verification.
- Similarity uses160-token excerpts in this experiment; the live application's
  different windowing must be calibrated separately.

Held-out strict reference-gate acceptance:

| Strategy | Accepted /16 | Accepted answers judged correct + complete by the separate audit |
|---|---:|---:|
| Baseline | 3 | 2/3 |
| Research-aware | 3 | 3/3 |
| Hierarchical + recursive | 2 | 2/2 |
| Hierarchical + semantic + structured | 2 | 2/2 |

This is too few acceptances to estimate reliable precision, especially given
correlated reviewer/auditor errors. Baseline q12 passed the peer reviewer but the
reference audit flagged unsupported additions to an otherwise correct answer.

All strategies still failed the strict empty-claims abstention contract on the
four unanswerable questions. Some answers verbally acknowledged missing evidence;
the separate audit credited that on1/4 cases in the first three arms and2/4 in
semantic/structured. **None of the16 unanswerable primary attempts passed the
strict gate.**

## 6. Confirmed model-judge error: do not trust the accuracy score alone

GloVe Table2's requested total accuracy is **75.0%**. A deterministic,
post-hoc numeric consistency check of calibration caseq04 found:

| Strategy | Explicit percentage(s) in the generated answer | Correct requested value present? | Separate model audit said |
|---|---|---:|---|
| Baseline | 95.2% | No | CORRECT |
| Research-aware | 75.9%,81.9%,75.9%,81.9%,82.9% | No | CORRECT |
| Hierarchical + recursive | 75.9% | No | CORRECT |
| Hierarchical + semantic + structured | 75.0% | Yes | CORRECT |

That confirms **three reference-audit false positives**. The judge's reasons
described the correct reference value rather than assessing the actual wrong
answer. All three wrong-value drafts were withheld by the strict primary gate;
they did not become verified answers.

The semantic/structured arm generated the right number, but cited an additional
non-supporting passage and was not approved by the peer reviewer. Thus better
table representation can recover the right value while citation binding still
fails.

This check is **not** a replacement full-set accuracy metric: it covers one
explicit numerical field, does not certify other answers, and leaves all frozen
primary metrics and thresholds unchanged. q04 belongs to calibration, so it does
not directly alter the held-out answer-score table. It does establish that the
absolute model-judged scores cannot be treated as ground truth.

See [numeric_consistency.json](numeric_consistency.json) and
[reference_audit.json](reference_audit.json). Do not promote a strategy based
only on its judge score.

## 7. Indexing and storage

| Strategy | Indexed child units | Parent units | Float64 vector-array size | Observed build + index time |
|---|---:|---:|---:|---:|
| Baseline | 143 | 0 | 0.838MiB | 5.37s |
| Research-aware | 262 | 0 | 1.535MiB | 4.66s |
| Hierarchical + recursive | 435 | 262 | 2.549MiB | 14.44s |
| Hierarchical + semantic + structured | 536 | 390 | 3.141MiB | 25.65s |

Cache reuse within the run favors later strategies, so build times are **not
clean cold-start comparisons**. Semantic paragraph embedding cost about20.99s.
Vector sizes exclude source text, JSON and parent storage. Very short
heading/tail units remain visible in the distributions.

## 8. Recommended next step

1. Shortlist **baseline and research-aware**, not an automatic switch to the
   previously favored recursive strategy.
2. Add the current live350-word/50-word-overlap chunker as a fifth control.
3. Repeat at least three generation seeds with independent, answer-level
   reference adjudication, especially numeric/table and unsupported-extra-claim
   cases.
4. Improve citation-to-claim binding, table-column interpretation and
   abstention separately from chunking. Full text does not fix those automatically.
5. Only then test the actual Chat refinement loop, its windows/thresholds,
   cold/warm latency and concurrent model usage.

## Reproducibility and safety

- [Experiment instructions](../../README.md)
- [Primary summary and exact controls](summary.json)
- [Per-question metric CSV](per_question.csv)
- [Source/extraction audit](extraction_audit.json)
- [Common-question paired analysis](paired_analysis.json)
- [Separate reference-aware model audit](reference_audit.json)
- [Numeric judge-consistency check](numeric_consistency.json)

Downloaded PDFs, frozen inputs and raw responses remain under ignored
`research\chat_chunking\local`. The earlier corpus/reports are retained.
**23 focused tests pass**, all24 references bind to the new corpus, and source
coverage is verified for every index. Only `research` files were changed;
the live backend, frontend, database, pins and embeddings were not modified.
