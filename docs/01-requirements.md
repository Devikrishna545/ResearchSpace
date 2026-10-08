# Research Assistant — Functional & Non-Functional Requirements

**Project:** Local-first Multi-Agent Research Assistant
**Version:** 1.0
**Status:** Draft for implementation

---

## 1. Product Summary

A privacy-preserving, local-first multi-agent system that helps a researcher discover, ingest,
analyse, compare and interrogate academic papers. All model inference runs on a self-hosted
Ollama server so that research content never leaves the user's infrastructure. Only public
scholarly metadata APIs are contacted over the network.

### 1.1 Core Concepts

| Concept | Definition |
|---|---|
| **Research Space** | A named, long-lived container holding one conversation thread, its pinned papers, notes and derived artefacts. Equivalent to a "project". |
| **Paper** | A bibliographic record (metadata + optional full text + parsed chunks + embeddings). |
| **Pin** | The act of attaching a Paper to a Research Space, making it part of that space's retrieval corpus. |
| **Note** | User-authored or agent-generated structured annotation linked to a Paper and a Space. |
| **Turn** | One user message + the system's grounded response, persisted in the Space. |

---

## 2. Functional Requirements

Priority key: **M** = Must (MVP), **S** = Should, **C** = Could, **W** = Won't (this release).
Phase key indicates target delivery phase (P1–P4).

### FR-1 Discovery & Search

| ID | Requirement | Pri | Phase |
|---|---|---|---|
| FR-1.1 | The system shall accept a free-text research topic and return relevant academic papers. | M | P1 |
| FR-1.2 | The system shall query multiple scholarly sources in parallel: arXiv, Semantic Scholar, OpenAlex, CORE, PubMed/PMC, CrossRef. | M | P1/P2 |
| FR-1.3 | The system shall deduplicate results across sources using DOI, arXiv ID, and normalised title+author fuzzy match. | M | P1 |
| FR-1.4 | The system shall support exact-paper lookup when the user supplies a paper title, DOI, arXiv ID, or PMID. | M | P2 |
| FR-1.5 | The system shall rank results semantically against the user's intent, not only by keyword match, recency or citation count. | M | P1 |
| FR-1.6 | The ranking shall combine: dense semantic similarity, cross-encoder rerank score, citation count, recency, and open-access availability, using a configurable weighted formula. | S | P1 |
| FR-1.7 | The system shall expose filters: year range, source, open-access only, venue, author, minimum citations. | S | P2 |
| FR-1.8 | The system shall display for each result: title, authors, year, venue, abstract, citation count, source, OA status, and a direct link. | M | P1 |
| FR-1.9 | The system shall support general web/knowledge-base search as a supplementary source for context that is not in paper indices. | C | P3 |
| FR-1.10 | The system shall cache external API responses per normalised query to reduce latency and respect rate limits. | M | P1 |
| FR-1.11 | The system shall degrade gracefully when one or more external sources are unavailable, returning partial results with a source-health indicator. | M | P1 |

### FR-2 Ingestion & Library

| ID | Requirement | Pri | Phase |
|---|---|---|---|
| FR-2.1 | The user shall be able to pin/attach any discovered paper to the active Research Space. | M | P1 |
| FR-2.2 | The user shall be able to upload a local PDF and have it treated as a first-class Paper. | M | P1 |
| FR-2.3 | The system shall retrieve open-access full text where legally available; otherwise it shall fall back to abstract + metadata and clearly label reduced coverage. | M | P1 |
| FR-2.4 | The system shall parse PDFs with layout awareness, preserving section headings, page numbers, tables and reference lists. | M | P1 |
| FR-2.5 | The system shall OCR scanned/image-only PDFs as a fallback. | S | P2 |
| FR-2.6 | The system shall chunk documents semantically (section/paragraph aware) with configurable size and overlap. | M | P1 |
| FR-2.7 | The system shall generate embeddings via the self-hosted Ollama embedding model and store them in a space-scoped vector collection. | M | P1 |
| FR-2.8 | Ingestion shall run asynchronously with visible progress states: queued → fetching → parsing → chunking → embedding → ready → failed. | M | P1 |
| FR-2.9 | The system shall deduplicate ingestion: a paper already embedded shall be reused across Spaces without re-embedding. | S | P2 |
| FR-2.10 | The user shall be able to unpin or delete a paper, which removes it from retrieval for that Space. | M | P1 |

### FR-3 Conversational Q&A (RAG)

| ID | Requirement | Pri | Phase |
|---|---|---|---|
| FR-3.1 | The user shall be able to ask natural-language questions answered strictly from the papers pinned to the active Space. | M | P1 |
| FR-3.2 | Every factual claim in an answer shall carry an inline citation resolving to paper + section + page + chunk. | M | P1 |
| FR-3.3 | Retrieval shall be hybrid: dense vector search plus BM25 sparse search, fused (RRF) and then cross-encoder reranked. | M | P3 |
| FR-3.4 | The system shall explicitly answer "not supported by the attached papers" rather than speculate when evidence is insufficient. | M | P1 |
| FR-3.5 | Answers shall be produced through the Phase 3 peer-review verification loop (see §4). | M | P3 |
| FR-3.6 | The system shall surface a confidence/groundedness score and the number of verification iterations performed. | S | P3 |
| FR-3.7 | The user shall be able to click any citation and view the exact source passage highlighted in context. | S | P2 |
| FR-3.8 | The system shall stream answer tokens to the UI as they are produced. | M | P1 |
| FR-3.9 | The user shall be able to scope a question to a subset of pinned papers. | S | P2 |

### FR-4 Comparison & Gap Analysis

| ID | Requirement | Pri | Phase |
|---|---|---|---|
| FR-4.1 | The system shall extract a structured profile per paper: problem, objective, method, dataset, metrics, results, limitations, future work. | M | P2 |
| FR-4.2 | The system shall generate a comparison matrix across any selected set of pinned papers. | M | P2 |
| FR-4.3 | The system shall identify commonalities (shared methods, datasets, findings, assumptions). | M | P2 |
| FR-4.4 | The system shall identify contradictions and disagreements between papers, with citations for both sides. | M | P2 |
| FR-4.5 | The system shall identify research gaps: unexplored combinations, acknowledged limitations not addressed elsewhere, missing baselines, under-studied populations/datasets. | M | P2 |
| FR-4.6 | Comparison output shall be exportable (Markdown, CSV, PDF). | S | P3 |
| FR-4.7 | Comparison results shall be cached and invalidated when the pinned set changes. | S | P2 |
| FR-4.8 | Gap analysis output shall also pass the peer-review verification loop. | S | P3 |

### FR-5 Notes & Annotation

| ID | Requirement | Pri | Phase |
|---|---|---|---|
| FR-5.1 | The system shall auto-generate structured notes per paper (summary, key contributions, methodology, results, limitations, relevance to the Space's topic). | M | P2 |
| FR-5.2 | The user shall be able to create, edit, and delete free-form notes attached to a Paper or a Space. | M | P2 |
| FR-5.3 | Notes shall be searchable and shall be retrievable as context in Q&A. | S | P2 |
| FR-5.4 | The user shall be able to highlight a passage and attach a note to it. | C | P3 |
| FR-5.5 | Notes shall be exportable per paper or per Space. | S | P3 |

### FR-6 Memory, Context & Sessions

| ID | Requirement | Pri | Phase |
|---|---|---|---|
| FR-6.1 | Conversations shall persist indefinitely and be resumable across application restarts. | M | P1 |
| FR-6.2 | Papers discovered or pinned in a Space shall remain bound to that Space. | M | P1 |
| FR-6.3 | The system shall maintain long-conversation context via rolling summarisation plus vector recall of earlier turns, without unbounded context growth. | M | P2 |
| FR-6.4 | The system shall maintain a per-Space "findings memory": accumulated conclusions, open questions and decisions. | S | P3 |
| FR-6.5 | The user shall be able to rename, archive, duplicate and delete a Research Space. | S | P2 |
| FR-6.6 | Full-text search across all conversations and notes shall be available. | C | P3 |

### FR-7 Administration & Model Management

| ID | Requirement | Pri | Phase |
|---|---|---|---|
| FR-7.1 | The system shall connect to a configurable self-hosted Ollama endpoint. | M | P1 |
| FR-7.2 | Chat model, embedding model, reranker model and verifier model shall be independently configurable. | M | P1 |
| FR-7.3 | The system shall expose health checks for Ollama, vector store, database, queue and each external API. | M | P1 |
| FR-7.4 | The system shall support multiple users with strict data isolation. | S | P4 |
| FR-7.5 | An evaluation dashboard shall report retrieval quality, groundedness, verification loop statistics and latency percentiles. | S | P4 |

---

## 3. Non-Functional Requirements

### NFR-1 Performance & Latency

| ID | Requirement | Target |
|---|---|---|
| NFR-1.1 | Time to first streamed token for a Q&A turn | ≤ 2.5 s (p50), ≤ 5 s (p95) |
| NFR-1.2 | Complete Q&A turn including verification loop | ≤ 12 s (p50), ≤ 25 s (p95) |
| NFR-1.3 | Discovery search results returned | ≤ 3 s (p50), ≤ 8 s (p95) |
| NFR-1.4 | Retrieval stage (hybrid search + rerank) | ≤ 800 ms (p95) |
| NFR-1.5 | Ingestion of a 20-page PDF end-to-end | ≤ 60 s (p95), asynchronous |
| NFR-1.6 | Comparison of 10 pinned papers | ≤ 90 s (p95), asynchronous with progress |
| NFR-1.7 | UI interaction responsiveness (non-inference) | ≤ 200 ms |

*Design note:* external API fan-out is parallel; embeddings are computed once and cached;
verification loop is bounded to a maximum iteration count so worst-case latency is deterministic.

### NFR-2 Accuracy & Quality

| ID | Requirement | Target |
|---|---|---|
| NFR-2.1 | Groundedness — every claim traceable to a retrieved passage | ≥ 95% of claims on attached-paper Q&A |
| NFR-2.2 | Answer correctness on curated evaluation set | ≥ 90% |
| NFR-2.3 | Citation precision — cited passage genuinely supports the claim | ≥ 95% |
| NFR-2.4 | Retrieval recall@10 on evaluation set | ≥ 90% |
| NFR-2.5 | Abstention correctness — system declines when evidence absent | ≥ 95% of unanswerable probes |
| NFR-2.6 | Hallucinated-citation rate (citation to non-existent/irrelevant source) | ≤ 1% |
| NFR-2.7 | Semantic ranking quality, nDCG@10 on labelled topic set | ≥ 0.80 |

*Design note:* these are engineered targets enforced by the Phase 3 verification loop and
measured continuously by the evaluation harness; they are not model guarantees.

### NFR-3 Scalability

| ID | Requirement |
|---|---|
| NFR-3.1 | API, orchestrator and worker tiers shall be stateless and horizontally scalable. |
| NFR-3.2 | Ollama inference shall run as an independently scalable GPU pool behind a load balancer. |
| NFR-3.3 | The vector store shall support ≥ 10M chunks with sub-second filtered search. |
| NFR-3.4 | The system shall support ≥ 100 concurrent active Research Spaces per node group. |
| NFR-3.5 | Ingestion workers shall scale on queue depth without affecting chat latency. |
| NFR-3.6 | Per-Space vector isolation shall be achieved via collection/namespace partitioning. |

### NFR-4 Privacy & Security

| ID | Requirement |
|---|---|
| NFR-4.1 | No paper content, note, or conversation shall be transmitted to any third-party LLM provider. |
| NFR-4.2 | Outbound network access shall be limited to an allow-list of scholarly metadata/full-text endpoints. |
| NFR-4.3 | All inference shall occur on the self-hosted Ollama deployment. |
| NFR-4.4 | Data at rest (database, vector store, uploaded PDFs) shall be encryptable. |
| NFR-4.5 | Authentication shall use JWT/OIDC; all API routes except health shall be authenticated. |
| NFR-4.6 | Strict tenant isolation shall be enforced at query level for every data access. |
| NFR-4.7 | User inputs and retrieved document text shall be sanitised to mitigate prompt injection from malicious PDFs. |
| NFR-4.8 | Agent tool invocations shall be validated against an allow-listed schema. |

### NFR-5 Reliability & Availability

| ID | Requirement |
|---|---|
| NFR-5.1 | Target availability 99.5% for the API tier. |
| NFR-5.2 | External source failures shall be isolated by circuit breakers and shall not fail the request. |
| NFR-5.3 | Ingestion jobs shall be idempotent and retried with exponential backoff (max 3 attempts). |
| NFR-5.4 | The verification loop shall be bounded and shall always return a best-effort, clearly-labelled answer. |
| NFR-5.5 | Database and vector store shall be backed up daily with point-in-time recovery. |

### NFR-6 Observability

| ID | Requirement |
|---|---|
| NFR-6.1 | Every agent hop shall emit a trace span (input, output, model, tokens, latency). |
| NFR-6.2 | Verification loop iterations, reviewer verdicts and rejection reasons shall be logged per turn. |
| NFR-6.3 | Retrieval diagnostics (queries, candidates, scores, selected chunks) shall be inspectable per answer. |
| NFR-6.4 | Latency, token throughput, GPU utilisation and queue depth shall be exported as metrics. |
| NFR-6.5 | Structured JSON logs with correlation IDs across API → orchestrator → agent → model. |

### NFR-7 Maintainability & Portability

| ID | Requirement |
|---|---|
| NFR-7.1 | Agents shall be independently testable units with typed input/output contracts. |
| NFR-7.2 | Model, vector store and paper-source integrations shall sit behind provider interfaces to avoid lock-in. |
| NFR-7.3 | Prompts shall be versioned, externalised from code, and diffable. |
| NFR-7.4 | The full stack shall run via a single `docker compose up` for local development. |
| NFR-7.5 | Minimum 80% unit-test coverage on agent and retrieval logic. |

### NFR-8 Compliance & Ethics

| ID | Requirement |
|---|---|
| NFR-8.1 | Only open-access or user-supplied full text shall be stored; paywalled content shall not be scraped. |
| NFR-8.2 | External API terms of use and rate limits shall be respected, with a polite User-Agent and contact email. |
| NFR-8.3 | Generated summaries shall always attribute the source paper. |
| NFR-8.4 | The UI shall state that outputs are AI-generated and require scholarly verification. |

### NFR-9 Usability & Accessibility

| ID | Requirement |
|---|---|
| NFR-9.1 | Citations shall be one click from claim to source passage. |
| NFR-9.2 | Long-running operations shall always show determinate progress. |
| NFR-9.3 | WCAG 2.1 AA conformance. |
| NFR-9.4 | Keyboard-first navigation for search, pin and chat. |

---

## 4. Phase 3 — Loop-Engineered Accuracy (Peer-Review Verification)

### 4.1 Objective

No answer reaches the user until a **peer reviewer agent** has independently verified it against
the retrieved evidence. If the reviewer rejects it, the answer is regenerated **with the reviewer's
specific corrective feedback** and re-verified, repeating until the reviewer approves or the
iteration budget is exhausted.

### 4.2 Loop Participants

| Agent | Responsibility |
|---|---|
| **Answer Agent (Generator)** | Produces a cited, evidence-grounded draft answer from retrieved context. |
| **Peer Reviewer Agent (Critic)** | Independently verifies the draft claim-by-claim against the same evidence. Runs on a separate prompt and may run on a different/larger model. Never sees the generator's reasoning — only the question, evidence and draft, to avoid confirmation bias. |
| **Refinement Controller** | Interprets reviewer verdicts, decides next action (accept / regenerate / re-retrieve / abstain), enforces the iteration budget and convergence rules. |
| **Retrieval Agent** | Re-invoked with reviewer-suggested query expansions when the failure is "evidence missing" rather than "reasoning wrong". |

### 4.3 Loop Flow

```
        User question
             │
             ▼
   ┌──────────────────┐
   │ Retrieval Agent  │  hybrid search → RRF fusion → cross-encoder rerank → top-K evidence
   └────────┬─────────┘
            ▼
   ┌──────────────────┐
   │  Answer Agent    │  draft answer + inline citations + per-claim evidence map
   └────────┬─────────┘
            ▼
   ┌────────────────────────────────────────────┐
   │        Peer Reviewer Agent (Critic)        │
   │  For each atomic claim, judge:             │
   │   • SUPPORTED    — evidence entails claim  │
   │   • PARTIAL      — overstated / imprecise  │
   │   • UNSUPPORTED  — no evidence             │
   │   • CONTRADICTED — evidence says otherwise │
   │   • MISCITED     — wrong citation target   │
   │  Emit: verdict, per-claim findings,        │
   │        corrective suggestions, missing-    │
   │        evidence query hints, score 0–1     │
   └────────┬───────────────────────────────────┘
            ▼
   ┌──────────────────────────┐
   │ Refinement Controller    │
   └───┬───────┬──────────┬───┘
       │       │          │
  APPROVED   REVISE   EVIDENCE_GAP
       │       │          │
       │       │          └──► back to Retrieval Agent with expanded queries ──┐
       │       └──► back to Answer Agent with reviewer feedback appended ──────┤
       │                                                                        │
       ▼                                                            (iteration n+1)
  Return answer + confidence + citations + iteration count
```

### 4.4 Loop Control Rules

| Rule | Specification |
|---|---|
| **LC-1 Iteration budget** | Maximum 3 refinement iterations (configurable 1–5). |
| **LC-2 Acceptance threshold** | Reviewer score ≥ 0.90 **and** zero UNSUPPORTED/CONTRADICTED/MISCITED claims. |
| **LC-3 Routing** | UNSUPPORTED/insufficient-evidence → re-retrieve. PARTIAL/MISCITED/overstatement → regenerate only. CONTRADICTED → regenerate with explicit contradiction notice. |
| **LC-4 Feedback carry-forward** | Each iteration receives the full history of prior reviewer findings to prevent regression on already-fixed claims. |
| **LC-5 Convergence guard** | If reviewer score fails to improve by ≥ 0.05 across two consecutive iterations, stop early (oscillation detection). |
| **LC-6 Exhaustion behaviour** | On budget exhaustion, return the highest-scoring draft, strip or flag unverified claims, and surface a clear low-confidence warning. Never silently return a rejected answer. |
| **LC-7 Abstention** | If after re-retrieval no supporting evidence exists, return an explicit "not answerable from the attached papers" with what *was* found. |
| **LC-8 Independence** | Reviewer prompt, temperature and (optionally) model must differ from the generator's to avoid correlated errors. Reviewer temperature ≈ 0. |
| **LC-9 Determinism** | Generator temperature ≤ 0.3 for factual Q&A; reviewer 0.0. |
| **LC-10 Auditability** | Every iteration (draft, verdict, findings, score, action) persisted and inspectable in the UI "Verification trail". |
| **LC-11 Latency guard** | Total loop wall-clock capped (default 20 s); on breach return best draft with a warning. |
| **LC-12 Escalation** | On iteration 3, the reviewer may be escalated to the larger model for a final adjudication pass. |

### 4.5 Reviewer Output Contract

```json
{
  "verdict": "APPROVED | REVISE | EVIDENCE_GAP | REJECT",
  "overall_score": 0.0,
  "claims": [
    {
      "claim_id": "c1",
      "claim_text": "...",
      "status": "SUPPORTED | PARTIAL | UNSUPPORTED | CONTRADICTED | MISCITED",
      "cited_chunk_ids": ["..."],
      "evidence_quote": "...",
      "issue": "...",
      "suggested_correction": "..."
    }
  ],
  "missing_evidence_queries": ["..."],
  "global_feedback": "...",
  "hallucination_flags": ["..."]
}
```

### 4.6 Applicability

The loop is mandatory for: Paper Q&A answers (FR-3.5), gap-analysis conclusions (FR-4.8),
and auto-generated paper notes. It is optional for: discovery result listing and UI-level
summarisation of already-verified content.

### 4.7 Loop Quality Metrics

| Metric | Purpose | Target |
|---|---|---|
| First-pass approval rate | Generator quality without help | ≥ 65% |
| Post-loop approval rate | End-to-end accuracy gate | ≥ 95% |
| Mean iterations per turn | Latency/cost control | ≤ 1.6 |
| Budget-exhaustion rate | Frequency of low-confidence returns | ≤ 5% |
| Reviewer false-approval rate (human-audited sample) | Reviewer reliability | ≤ 3% |
| Added latency from loop | Cost of accuracy | ≤ 6 s (p50) |

---

## 5. Acceptance Criteria (Release Gates)

1. All **M**-priority functional requirements for the phase are implemented and demonstrable.
2. Evaluation harness reports NFR-2 targets met on the curated gold-standard question set.
3. p95 latency budgets in NFR-1 met under 20 concurrent users.
4. Zero outbound transmission of paper/conversation content verified by network egress audit.
5. Verification trail visible and complete for every Phase 3 answer.
6. Loop metrics in §4.7 met over a minimum 500-turn evaluation run.
