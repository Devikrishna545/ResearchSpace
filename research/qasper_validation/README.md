# QASPER + full-PDF validation

## Registered design

- **200 questions x3 arms x3 seeds =1,800 answer attempts.**
-120 QASPER questions:20 official development questions for calibration,
 100 official test questions for held-out evaluation.
-80 supplementary full-PDF questions:20 calibration,60 held-out.
-126 documents: one independent QASPER paper per sampled question, plus six
 original full PDFs from the preceding experiment.
- Documents are disjoint between calibration and evaluation. QASPER questions
 are paper-scoped, matching its official task. Supplementary questions retrieve
 across their split's PDF pool, including four cross-paper cases.
- QASPER sampling is seeded and stratified before retrieval/model evaluation.
 All reference annotations are preserved; examples are not selected by whether
 they are easy to retrieve or score.
- Official v0.3 archives, downloaded official evaluator, and input hashes are
 retained locally. QASPER data is CC BY4.0; the evaluator repository is
 Apache2.0. Sources: [dataset](https://huggingface.co/datasets/allenai/qasper),
 [official implementation](https://github.com/allenai/qasper-led-baseline).

| Track | Calibration | Held-out |
|---|---:|---:|
| QASPER extractive |8|40|
| QASPER free-form |4|25|
| QASPER yes/no |4|15|
| QASPER unanswerable (majority reference type) |4|20|
| Source-checked PDF supplement |20|60|

The five initially unmatched QASPER examples referred to section headings.
Representing the dataset's actual section-heading units, along with its abstract,
paragraphs and figure/table captions, resolved all selected evidence mappings.
No question was dropped or replaced because of alignment. Figure pixels are not
interpreted; this track is annotated full text, not fresh PDF extraction.

## Chunkers and controls

1. **current_chat:** the production's actual pure350-word/50-word-overlap helper,
   loaded without importing application/database modules. Common source offsets
   and page/section boundaries are retained. This controls the existing word
   policy, **not** all live PDF heading-detection/retrieval/refinement behavior.
2. **baseline:**650 benchmark tokens,81-token overlap (12.46%).
3. **research_aware:** section/subsection/paragraph grouping,800-token maximum.

Same fixed hybrid ranker, top8 contexts,2,400 serialized evidence tokens,
`llama3.2:3b` answers, `nomic-embed-text:latest` embeddings and
**`gemma4:latest` reviewer**. Temperature0; seeds42/43/44. At temperature0,
different seeds may produce identical answers; these are repeated executions,
not200x3 independent questions. Model digests are frozen.

The answer prompt requests a shortest direct `answer` plus separately cited
`claims`. This enables official-style Answer F1 without scoring a long explanatory
answer as though it were an extractive span. Every arm uses the same prompt;
results are not a directly comparable continuation of the earlier prompt.

The unchanged word control can exceed the embedding model's native token limit
on mathematical PDFs: a325-word Tensor window measured1,908 benchmark tokens and
was rejected with `input length exceeds the context length`. Truncation is disabled.
A failed paper is explicitly marked unavailable in that arm's index, consistent
with whole-paper ingestion failure. Other successfully indexed papers remain
available. Failed questions stay in denominators; controls are not silently
rechunked to make them pass. Index failures are part of the result.

## Labels and scoring

- QASPER answers/evidence are independently annotated by dataset practitioners.
  Token Answer F1 and paragraph Evidence F1 are tested against the downloaded
  official evaluator, including all reference answers, yes/no, unanswerable,
  duplicate-item and empty-set behavior.
- Context/citation offsets map back to original paragraph/heading/caption strings.
  Any overlapping selected source unit counts as selected for paragraph F1;
  that metric alone does not establish that the full unit was in the prompt.
- Both all-evidence and text-only Evidence F1 are reported.
- The80 supplementary labels are assistant-authored and checked against exact
  PDF source anchors. **They are not independently human-adjudicated gold.**
  Calibration uses Guppy/QPPL; held-out uses GloVe/word2vec/Tensor/NISQ.
  Some questions share source passages, so statistical uncertainty must respect
  document/question clustering, not treat every claim as independent.
- Supplementary numerical regex checks and forbidden table-column confusions are
  separate from token F1. They are deterministic field checks, not a proof of
  every asserted fact or a replacement for human correctness review.
- Peer review reports supported claims, exact quote provenance, valid IDs and
  citation-excerpt cosine. It is **not** the primary answer-accuracy judge.
-28 score/cosine pairs are examined on calibration only; reference0.90/0.65
 remains selected until independently adjudicated accepted-answer safety exists.
 A95% safety target cannot be certified by this reviewer, lexical F1 or the
 assistant-authored supplementary labels.
- At completion, accepted held-out answers are exported to an ignored
 `human_adjudication_queue.json` with blank reviewer/verdict fields.
- Errors and abstentions stay in the scores. Reports are separated by track,
 arm and seed. Partial reports are explicitly labelled incomplete.

## Commands

From `research`, using the existing isolated research environment:

```powershell
.\.venv\Scripts\python.exe -m qasper_validation.data download
.\.venv\Scripts\python.exe -m qasper_validation.data freeze
.\.venv\Scripts\python.exe -m pytest qasper_validation\tests chat_chunking\tests -q
.\.venv\Scripts\python.exe -m qasper_validation.runner smoke --run qasper-pdf-20261002-v2
.\.venv\Scripts\python.exe -m qasper_validation.runner run --run qasper-pdf-20261002-v2
.\.venv\Scripts\python.exe -m qasper_validation.runner status --run qasper-pdf-20261002-v2
```

Download resumes verified files; dataset freeze is write-once. Skip it when
`local\dataset.json` already exists. The smoke run evaluates one preregistered
calibration extractive question for all three arms at seed42. Those three records
are reused unchanged by the full run, not cherry-picked or retried.

The worker holds an exclusive `worker.lock`; do not start a second worker for the
same run. After an abnormal machine/process crash, verify the recorded PID is no
longer running before removing that one resolved lock file. Resume with `run`.
Changing code, frozen inputs or model digests requires a new run name.

An actual three-arm protocol preflight also verified answer generation and
Gemma4 review on one fixed calibration question. Its six model-call records are
kept separately under `protocol_preflight`; they are not counted among the1,800
primary attempts or used to select strategies.

The authorized full worker runs independently after the chat session ends. After
the primary command finishes, the launcher invokes:

```powershell
.\.venv\Scripts\python.exe -m qasper_validation.audits.final_analysis `
  --run qasper-pdf-20261002-v2
```

That adds question-paired confidence intervals on the100 distinct held-out QASPER
papers after averaging seed repetitions, category diagnostics and model-loading
timings. It does not claim60 independent PDF-document clusters or automatically
promote a winner. Partial/preflight scores remain separate.

Status is stored at `local\runs\qasper-pdf-20261002-v2\status.json`.
Final output is written automatically to `reports\qasper-pdf-20261002-v2\REPORT.md`,
`summary.json` and `per_question.csv` after all1,800 results exist. Do not interpret
the smoke-run `PARTIAL.md` as the experiment's findings.

The original preparation stopped before retrieval/generation because Windows
temporarily locked the frequently replaced progress file. A bounded status-file
retry was added and the run restarted as `qasper-pdf-20261002-v2`. Input labels
and evaluation controls did not change. Previously generated, model/text-keyed
embedding cache entries are reused; index timings are therefore warm/cache-aware,
not cold-build performance claims.

Raw datasets, source text, vectors and model responses remain ignored under
`local`. No production data is written; no server is restarted or production
model setting changed. Only local Ollama compute is shared, so interactive Chat
may be slower while the benchmark runs.
