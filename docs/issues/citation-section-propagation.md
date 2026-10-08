# Issue draft: prevent incorrect section labels in paper readers and future citations

**Status:** partially mitigated on local `main`, not filed as a GitHub issue.
The project's GitHub account was unavailable when filing was attempted.
The current live database has **zero stored citations**: no old chat
citation is currently showing a wrong section. The defect was still
user-visible in reader section labels and **would** have propagated into
new chat citations for affected stored chunks.

## Root cause and fix for new ingests

The former `_detect_section` searched the first few words of an already
flattened chunk for a section cue and returned the previous label on
failure. `_chunk_words` had removed the original PDF line breaks before
heading detection; spurious cues could label most of a paper as one
section.

As of local commit `a4be2d0`, PDF text is segmented on genuine heading
lines *before* flattening. Headings carry their original wording beside
a conservative canonical label. Unknown sections remain unknown; reader
and citation UI say so explicitly. A numbered outline is required
before accepting numbered headings, avoiding medical tables and
bibliography entries that resemble section numbers. Medical and
humanities heading coverage remains partial, and scanned/image PDFs
remain text-free unless OCR is performed elsewhere. No GROBID service
was added.

## Existing records and controlled repair

The live corpus originally had 167 chunks, 86 with labels and 81
unknown. The word2vec paper, *Efficient Estimation of Word
Representations in Vector Space*, had 26/27 chunks incorrectly
labelled `Result`. *Reducing hallucination in structured outputs*
had 24/29 labelled `Method` and two labelled `Result`.

After a fresh WAL-consistent backup and **100% exact chunk-to-original-PDF
alignment for each target (27/27 and 29/29)**, an approved transaction
updated **only** the `section` values of these existing chunks and
matching citation-section snapshots. Their chunk IDs, text, pages,
embeddings and all paper/pin/note/turn/account/session identities were
preserved. Word2vec is now 6 true-heading sections and 21 unknown;
the structured-output paper is 6 true-heading sections and 23 unknown.
The database stays at Alembic head `0005_openalex_consent` with the same
one pre-existing foreign-key finding, two sessions, and all row counts
unchanged. The in-memory vector store was rehydrated after the update.
There were zero existing citations to update; a synthetic citation in
a disposable rehearsal proved its ID and chunk link survive a
section-only update.

**GloVe remains affected.** Its 33 stored chunks are all heuristically
labelled (16 `Method`, 13 `Related Work`, three `Introduction`, one
`Conclusion`), but only **17/33** align with the available public PDF
variant. It was **not repaired**. A user may choose to re-ingest an
accessible copy later, but any such operation must first plan for
preserving existing paper/chunk IDs and downstream references; do not
delete-and-recreate it automatically or guess a section from a
different PDF.

## Remaining acceptance criteria

- Determine whether the exact original GloVe PDF can be recovered for
  a separate 100%-alignment section-only repair. Otherwise leave
  historical labels flagged as heuristic/uncertain or accept a
  user-authorized re-ingest with a citation/annotation preservation plan.
- Keep reader/citation labels truthful: an unknown heading is displayed
  as unknown, not inherited from the previous chunk.
- Validate future citation sections against source PDF structure and
  maintain regression cases for prose cues, medical numbered lists,
  bibliography entries, uncertain headings and page transitions.
