# Identifiable-paper ranking evaluation

`ranking_queries.json` fixes 24 arXiv-identified targets in advance: eight
exact-title, eight descriptive, and eight vocabulary-mismatch queries. Matching
uses canonical arXiv IDs or DOIs, **never title similarity**. The vocabulary
mismatch category exposes weaknesses that deterministic lexical ranking may not
fix; do not drop its missing-target queries.
Two exact-title targets also list their verified published DOIs because
OpenAlex/Crossref candidates can carry the DOI but omit the arXiv identifier.
Both aliases identify the same paper; other works sharing a title do not count.
When a verified published DOI and arXiv preprint survive as two distinct
candidate records, the evaluator counts the best rank of that same target
and records `target_match_count`; it never matches on title alone.

From `backend`, run:

```powershell
.\.venv\Scripts\python.exe -m scripts.eval_ranking snapshot --report evaluations/reports/baseline.json
.\.venv\Scripts\python.exe -m scripts.eval_ranking cached --compare-to evaluations/reports/baseline.json
.\.venv\Scripts\python.exe -m scripts.eval_ranking live
```

`snapshot` runs the same QueryPlanner → SourceRegistry fan-out → Normalizer →
Deduplicator → RankingAgent path as discovery (without cutting the results off
before evaluation). It fetches 20 candidates per source and waits at least
3.2 seconds between fresh queries. It writes one candidate file per query plus
a checksummed manifest under ignored `backend\data\ranking-eval\`. Interrupted
snapshots resume without refetching completed queries; a completed snapshot
cannot be silently overwritten. These local fixtures may contain source
abstracts and should **not** be committed or shared. `cached` verifies fixture
hashes and performs no API requests. `live` re-fetches for reality checks
without changing the frozen fixtures. For a consented OpenAlex search, the
optional `--consented-user <user-id>` flag reads only that member's granted
address locally; the address is never written to fixtures, metrics or output.
Without the flag OpenAlex stays unidentified, even if an admin opted in.

Reports count targets absent from the candidate set separately from targets
present but ranked below 10 or 20. Recall@10, recall@20 and MRR use **all**
queries (absent target = miss/zero reciprocal rank); median and mean rank
apply only to present targets and are labeled accordingly. Present-only
recall@10/@20 and MRR are also reported so ranking changes can be distinguished
from retrieval failures. The per-query table reports candidate count, presence
and target rank. Use `cached --compare-to
<earlier-report>` for rank-before/rank-after deltas on the **same** fixtures;
never interpret changes between independently fetched live candidate sets as
isolated ranking improvements.

## Frozen baseline before ranking changes

The initial ID-only target list marked two exact-title targets absent because
the returned records carried only their published DOIs, not their arXiv IDs.
Crossref confirmed those DOIs identify the **same** work (title and first
author match the arXiv work). The raw candidate arrays were not changed or
refetched. The original snapshot/report remain in the ignored local
`backend\data\ranking-eval-initial-identifiers\`; the full before/after
accounting and both DOI mappings are committed in
`reports\doi-alias-audit.json`.

| Target definitions | Absent / 24 | Recall@10 | Recall@20 | MRR | Present-only recall@10 | Present-only MRR | Mean present rank |
|---|---:|---:|---:|---:|---:|---:|---:|
| Original arXiv-only | 16 | 0.292 | 0.333 | 0.235 | 0.875 | 0.706 | 4.625 |
| Corrected (two verified DOI aliases) | 14 | 0.375 | 0.417 | 0.319 | 0.900 | 0.765 | 3.900 |

The corrected dataset and report in `reports\baseline.json` are frozen for
all subsequent ranking steps. Any future target correction requires rerunning
**every** step on the newly identified dataset, not silently changing one
step's denominator. All eight vocabulary-mismatch targets are absent from
their candidate pools, so even a perfect reranker cannot rescue that
category. Candidate retrieval/query expansion is a separate future decision;
this branch changes only deterministic ordering of candidates that exist.

### Recency audit (disabled by default)

`reports\recency.json` tests a capped 0–0.06 boost over ten years; recall@20
fell from 0.417 to 0.375 and present-only MRR from 0.765 to 0.637. This query
set deliberately targets famous landmark papers, often older than newer
competitors, so the regression does **not** show that recency is useless when
someone requests the *latest* work. It does show harm on this set and provides
no measured benefit. The signal remains available behind
`RANKING_RECENCY_WEIGHT` (0 by default, maximum 0.06), and
`reports\recency-disabled.json` verifies default behavior matches the frozen
baseline exactly. A separate benchmark of explicit recent-work intent would
be required before enabling it; this branch does not create or tune one.

### Abstract availability audit

The original scorer already counted the union of available title and
abstract tokens and **never added a zero-valued abstract penalty**. An
abstract-bearing record has more opportunities for lexical matches; that is
an inherent field-availability asymmetry rather than a removable penalty.
The parity unit test confirms that a paper without an abstract ties the
same-title paper whose abstract supplies no additional query evidence.
`reports\abstract-availability-audit.json` quantifies the frozen candidate
and present-target groups before deciding whether any compensating title
weight would be justified. No arbitrary missing-abstract bonus or per-field
blend was added.

Across 24 frozen query pools there are 1,533 deduplicated candidate
appearances: 1,094 (71.4%) have no abstract and 439 do. The no-abstract group
has mean score 0.513 and mean rank 36.9; abstract-bearing candidates average
0.641 and rank 23.6. Those group differences **do not establish causation**:
source, citations and relevance differ. Of the ten present target appearances,
two have no abstract (`exact-resnet` and `exact-segment-anything`), and both
rank **first**. No present target was demonstrably outranked because it lacked
an abstract. Step verdict: **NOT NEEDED on this evidence**. The parity test
protects against accidentally introducing a zero-field penalty, and
`reports\abstract-availability.json` records exact frozen-baseline metric
parity. A future metadata-fairness study would need independent relevance
labels rather than a new weight tuned on these landmark queries.

### Stopword audit and cumulative default

`reports\stopwords.json` tests removal of 22 ordinary English function words
from the query overlap denominator. An all-stopword query keeps its original
terms. Relative to the **corrected baseline with recency disabled**, this
variant moves `descriptive-reasoning` from rank 20 to 25. Recall@20 drops
from 0.417 to 0.375; present-only recall@20 drops from 1.0 to 0.9. There is
no measured benefit on the other nine present targets. Its implementation
is retained for audit behind `RANKING_REMOVE_STOPWORDS=false` by default,
without changing the word list to fit these 24 targets.

| Frozen run | Absent / 24 | Recall@10 | Recall@20 | MRR | Present-only recall@10 | Present-only recall@20 | Present-only MRR | Mean present rank |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Corrected baseline | 14 | 0.375 | 0.417 | 0.319 | 0.900 | 1.000 | 0.765 | 3.900 |
| Recency opt-in alone | 14 | 0.375 | 0.375 | 0.265 | 0.900 | 0.900 | 0.637 | 4.600 |
| Abstract audit (no score change) | 14 | 0.375 | 0.417 | 0.319 | 0.900 | 1.000 | 0.765 | 3.900 |
| Stopwords opt-in alone | 14 | 0.375 | 0.375 | 0.318 | 0.900 | 0.900 | 0.764 | 4.400 |
| Cumulative **enabled** steps (none) | 14 | 0.375 | 0.417 | 0.319 | 0.900 | 1.000 | 0.765 | 3.900 |

`reports\step-comparison.json` contains all 24 target-presence flags and
rank-before/rank-after values for **each** step; this table is not calculated
from changing candidate sets. No tested scoring change individually helped,
so the cumulative default in `reports\cumulative.json` intentionally equals
the baseline. In particular, all eight vocabulary-mismatch targets are
missing from the candidates. Semantic reranking alone would recover none of
them. Query expansion or better candidate retrieval is a higher-value
future hypothesis, not implemented or benchmark-tuned on this branch.

## Recall investigation: DataCite identifier enrichment (separate branch)

An arXiv DataCite DOI `10.48550/arXiv.<id>` encodes the same preprint's
arXiv identifier. `Normalizer` now fills a missing arXiv ID from **only**
this exact DOI namespace (including versioned and old-style IDs); published
or unrelated DOIs never imply an arXiv ID. If a record supplies an explicit
conflicting arXiv ID, normalization fails rather than merging it. The
deduplicator can now combine an OpenAlex DOI-only preprint with its arXiv
record by authoritative ID instead of fuzzy title. No existing paper rows
or candidate fixtures were changed. A read-only inspection of the current
live owner-scoped corpus found no DataCite DOI rows and no split DOI/arXiv
identity pairs, so no existing uniqueness collision was identified; future
split imports would still require review rather than in-place rewriting.

| Frozen 24-query run | Absent | Recall@10 | Recall@20 | MRR | Present-only recall@10 | Present-only recall@20 | Present-only MRR |
|---|---:|---:|---:|---:|---:|---:|---:|
| Main default | 14 | 0.375 | 0.417 | 0.319 | 0.900 | 1.000 | 0.765 |
| DOI-to-arXiv identification | 12 | 0.375 | 0.458 | 0.360 | 0.750 | 0.917 | 0.720 |

`reports\identifier-enrichment.json` records the per-query before/after
ranks. `descriptive-qlora` becomes identifiable at final rank **70** and
`mismatch-resnet` at rank **20**. Both DOI-only records were **already in the
frozen candidate sets**: this is an identification correction, not
additional retrieval. Other rank shifts (e.g. exact diffusion 10→2)
reflect identifier-aware deduplication or selecting the best verified
preprint/published alias, not a changed ranker or new API candidates.
The drop in present-only MRR is partly a denominator effect from newly
recognizing a rank-70 target. Ten of the originally absent targets remain
absent; no semantic/embedding reranking was implemented here.
