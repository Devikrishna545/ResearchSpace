# Research experiments

This directory contains reproducible, opt-in experiments. Nothing here is imported
by the application, started by its launcher, or applied to production settings.

- [Chat chunking benchmark](chat_chunking/README.md): four chunking strategies,
  frozen local paper evidence, retrieval/answer evaluation, and threshold analysis.
- [Completed pilot results](chat_chunking/reports/pilot-20261002-v2/REPORT.md).
- [Full-PDF follow-up results](chat_chunking/reports/fullpdf-20261002-v2/REPORT.md):
  six downloaded originals, all88 pages processed, comparative results and
  reviewer-reliability checks.
- [QASPER + full-PDF validation](qasper_validation/README.md):
 200 document-disjoint questions, the current Chat word policy and two shortlisted
 candidates, official-score parity, three seeds and resumable1,800-attempt execution.
- Each experiment keeps its own environment, fixtures, caches, and results.
- Read application data with read-only connections; never migrate or write it.
- Do not commit papers, source excerpts, account data, or generated raw responses.
- Promote a result to the application only through a separately approved change.
