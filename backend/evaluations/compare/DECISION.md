# Compare slice: measured stop decision

**Status: historical research record, not a shipped Compare implementation.**
The shipped Compare module now follows the grounded design that grew out of
these findings; see [docs/compare-workflow.md](../../../docs/compare-workflow.md).
This note was carried forward from the unmerged `compare-rebuild` experiment.
The production app on `main` has not adopted its elaborated comparison or
side-by-side UI. Measurements used three runs per group with installed local
models and a WAL-consistent disposable SQLite copy; the existing historical
report was one real run, not a comparable three-run baseline.

## What was tried

1. **Compare then cite.** A bounded map call per dimension supplied real
   source chunks to `llama3.2:3b`, followed by a short reduce. The first
   parser required nested `cells` and plural `commonalities`, while the
   model reliably emitted valid JSON with top-level `P1`/`P2` and singular
   `commonality`. Correcting this shape mismatch changed map parse success
   from 0/18 to 7/7 per full-text run, producing three findings per run.
   The initial 0/18 was a **parser defect**, not proof of model incapacity.
2. **Ground the claim, not only its quote.** All cited IDs resolved to real
   supplied chunks and 9/12 quotes were copied verbatim. Yet 12/12
   *claims* failed against their cited chunks: best length-matched
   sliding-window cosine 0.371–0.544. A 0.65 threshold was justified by
   independent measured separation between faithful compression (0.702)
   and plausible-but-absent text (0.553), not tuned to save the output.
   Windowing recovered none. One mixed pair attached a herbal abstract
   to a claim about word representation.
3. **Filter unsupported evidence.** Dropping unverified links while
   keeping findings with only one paper's remaining evidence preserves
   all three full-text and one mixed finding per run, including the false
   mixed finding. A *commonality* needs evidence from both papers; that
   correct policy leaves **zero cross-paper survivors** in every run.
4. **Extract then compare, scratch-only.** Gemma3 bound 22 verified
   statements per full-text run to real chunks. The compare step then
   asserted agreement using statement IDs from only one paper, which
   the code gate rejected in all three runs. In this particular
   extraction prompt, the 3B model returned parsed empty lists on
   11/12 calls per run. This does **not** establish that the model
   cannot do factual extraction under a different prompt or tolerant
   output normalizer. No product extract-then-compare code was added.
5. **Grounded side-by-side, scratch-only.** Gemma3 filled 12/12
   full-text paper/dimension cells over three runs with 22 source-bound
   statements each. Spot checks found off-dimension statements:
   an equation in DATASET, publication boilerplate in RESULTS, and a
   favorable property in LIMITATIONS. Grounding to a chunk does not prove
   a statement answers the requested dimension. In this specific
   prompt, the 3B model left eligible dimensions without both papers'
   statements.
6. **Embedding dimension-relevance guard: rejected.** Comparing
   statements with natural-language dimension descriptions using
   `nomic-embed-text` did not separate relevant from off-dimension text.
   Genuine examples scored 0.386–0.609 (mean 0.522), while irrelevant
   ones reached 0.507 (mean 0.454). Publication boilerplate scored
   0.507 for METHOD, above a genuine method statement at 0.386.
   A cutoff cannot keep the latter while rejecting the former.
7. **Historical section labels: unfit as a selector.** Before the
   document-structure repair, only 86/167 chunks (51%) had labels,
   with no `Dataset`, `Metrics`, `Limitations` or `Problem` labels.
   Word2vec had 26/27 chunks wrongly marked `Result`. New PDF ingests
   now detect genuine heading lines before flattening, and an approved
   section-only live repair corrected word2vec and one other fully
   aligned paper. GloVe's historical labels remain uncertain because
   only 17/33 chunks matched the available PDF variant. True section
   detection is useful but partial, especially across page boundaries
   and non-numbered document formats; it is not by itself a
   dimension-relevance or entity-type validator.

## Decision and limitations

Do **not** describe the experimental elaborated findings as verified or
merge the unmerged Compare synthesis code based on its yield alone. It
had no independent peer-review pass, so its deliberately assigned
confidence `0` is not comparable to the historical profile-only
report's `0.571` (which itself fell below the `0.90` acceptance
threshold). The reduce step selected map findings by text; it did not
catch semantic claim/citation mismatch. The code-side grounding
detector and two-paper support rule were the actual safety guards.

A side-by-side view of source-bound statements remains a possible
direction **only after** evaluating deterministic junk exclusion,
dimension/type validation, honest empty cells and a background job
for the additional calls. Never turn a lexical overlap into a claim
of agreement. No model-generated "both papers agree" sentence should
ship on the present evidence. No LLM judge, RAM/VRAM heuristics,
cross-model second opinion, citation-graph recommendations or other
later workstreams were implemented.

The original sanitized Layer 1 measurements are committed on the
unmerged `compare-rebuild` branch in `reports/*.json`; private raw
diagnostics remain outside Git. This documentation-only branch does
not bring over that experimental code or its report artifacts.
The section-label issue is tracked separately in
`docs/issues/citation-section-propagation.md`: zero stored chat
citations were affected at the time of the repair, although old
reader labels and prospective citations were at risk.

## Addendum: controlled extraction checks (2026-09-28)

These are new measurements, not a retroactive reinterpretation of the
three-run experiments above.

### Shape-tolerant parsing is a prerequisite

Asked for `{"datasets":[{"name":"..."}]}`, gemma3 returned valid JSON
as bare strings: `{"datasets":["Google News corpus","CBOW architecture"]}`.
A parser calling `.get("name")` on each value treated this as a model
failure. It is the **same defect class** as the original 0/18 map result:
correct data in an unanticipated JSON shape. Several earlier
"model incapacity" measurements were affected by a parser defect and
must not be generalized without inspecting raw responses.

**Future parsing proposal (not implemented):** normalize bare strings
and objects, singular/plural keys, top-level paper-label maps and
nested `cells`, and `items`/`findings`/`results` aliases. Test with
captured verbatim responses, including the unexpected but valid
shapes, rather than scoring only one requested schema.

### Corrected variance claim: fixed-seed output was identical

With the seed fixed and parser shape-tolerant, **5/5** word2vec dataset
queries produced **identical output**. The previously reported
run-to-run variance in that test was a broken parser, not stochastic
model behavior. The earlier recommendation to use self-consistency
voting against that supposed variance was **wrong**: do not pay
roughly 3x latency voting over identical output. This does not claim
that every model and prompt is deterministic without a fixed seed.

### Precision and entity type remain the gap

The model extracted the valid named dataset **"Google News corpus"**
in **5/5** runs, but also extracted **"CBOW architecture"** as a
dataset in **5/5**. CBOW is an architecture, not a dataset. Both
phrases occur in the chunk, so chunk grounding cannot reject the
type error. Voting would repeat it. The GloVe chunk mentioning
"wikipedia" returned **zero** datasets in 5/5 runs; that may be
correct if the mention is in Related Work rather than describing
GloVe's own training data. Inspect its source context before counting
zero as a miss.

**Future product proposal (not implemented):** extract narrow, named
facts *per paper*, validate each value's requested entity type
(dataset versus architecture, metric versus method), then compute
well-defined comparisons such as a shared-dataset set intersection
**in code**. This prevents a model from inventing a cross-paper
agreement, but type validation and contextual ownership of a
mention still need their own evaluation. Heading-aware PDF parsing
has removed the proven flattening defect; the present bottleneck is
precise extraction and validation, not a larger PDF service or a
model-authored synthesis prompt. Paragraph-aligned chunk tuning is
minor future work, not part of this decision.
