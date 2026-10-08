# Research Assistant — Architectural Analysis

**Version:** 1.0
**Companion documents:** `01-requirements.md`, `03-file-structure.md`

---

## 1. Architectural Drivers

The architecture is shaped by six forces, in priority order:

| # | Driver | Architectural consequence |
|---|---|---|
| 1 | **Privacy — research must not leave the machine/network** | Self-hosted Ollama only; no third-party LLM SDKs; egress allow-list; provider abstraction so no cloud model can be configured accidentally. |
| 2 | **Accuracy ≥ 90%, groundedness ≥ 95%** | Evidence-first RAG; mandatory peer-review verification loop; per-claim citation mapping; evaluation harness as a first-class subsystem. |
| 3 | **Low latency** | Parallel source fan-out; aggressive multi-tier caching; streaming; bounded verification loop; small model for routine turns, large model reserved for synthesis/adjudication. |
| 4 | **Scalability** | Stateless API/orchestrator; separate GPU inference pool; queue-backed ingestion workers; sharded vector store. |
| 5 | **Long-lived, connected research context** | Research Space as the aggregate root; durable conversation + pinned-paper binding; hierarchical memory (recent verbatim + rolling summary + vector recall). |
| 6 | **Heterogeneous scholarly sources** | Source-adapter pattern with a normalised `Paper` canonical model; circuit breakers per source. |

---

## 2. System Context (C4 Level 1)

```
                         ┌─────────────────────────────────────────┐
                         │            Researcher (User)            │
                         └────────────────────┬────────────────────┘
                                              │ HTTPS / WSS
                         ┌────────────────────▼────────────────────┐
                         │      Research Assistant Platform        │
                         │  (self-hosted, inside user's network)   │
                         └───┬──────────────────────────────┬──────┘
                             │                              │
        ┌────────────────────▼──────────┐      ┌────────────▼─────────────────┐
        │  External Scholarly Sources    │      │   Ollama Inference Server    │
        │  arXiv · Semantic Scholar ·    │      │   (self-hosted GPU node/s)   │
        │  OpenAlex · CORE · PubMed ·    │      │   chat · embed · rerank ·    │
        │  CrossRef · Unpaywall          │      │   verify                     │
        │  (metadata + OA full text only)│      └──────────────────────────────┘
        └────────────────────────────────┘
                     ▲
                     │  outbound, allow-listed, metadata queries only
                     │  NEVER: user questions verbatim, notes, private PDFs
```

**Trust boundary:** everything except the scholarly-source block runs inside the user's
network. Outbound traffic carries only search keywords and identifiers — never conversation
content, notes, or uploaded document text.

---

## 3. Container View (C4 Level 2)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                            PRESENTATION TIER                                  │
│  Next.js / React SPA — Chat · Library · Compare Matrix · Notes · Verification │
│  trail viewer · Source-passage highlighter                                    │
└───────────────────────────────┬──────────────────────────────────────────────┘
                                │ REST + WebSocket (streaming)
┌───────────────────────────────▼──────────────────────────────────────────────┐
│                          API / GATEWAY TIER  (stateless, N replicas)          │
│  FastAPI · AuthN/AuthZ (JWT) · rate limiting · request validation ·           │
│  tenant scoping · SSE/WS streaming · OpenAPI contract                         │
└───────────────────────────────┬──────────────────────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────────────────────┐
│                     ORCHESTRATION TIER  (LangGraph, stateless)                │
│  Supervisor graph · state machine per turn · conditional routing ·            │
│  checkpointing to Postgres · trace emission                                   │
└───┬───────────┬────────────┬───────────┬────────────┬────────────┬───────────┘
    │           │            │           │            │            │
┌───▼────┐ ┌────▼─────┐ ┌────▼─────┐ ┌───▼──────┐ ┌───▼──────┐ ┌───▼────────┐
│Discovery│ │Ingestion │ │Retrieval │ │ Answer   │ │ Peer     │ │ Compare /  │
│ Agent   │ │ Agent    │ │ Agent    │ │ Agent    │ │ Reviewer │ │ Gap Agent  │
│         │ │          │ │          │ │          │ │ Agent    │ │            │
└───┬────┘ └────┬─────┘ └────┬─────┘ └───┬──────┘ └───┬──────┘ └───┬────────┘
    │           │            │           │            │            │
    │      ┌────▼─────┐      │      ┌────▼────────────▼────────────▼───┐
    │      │  Notes   │      │      │   Refinement Controller (loop)   │
    │      │  Agent   │      │      └──────────────────────────────────┘
    │      └────┬─────┘      │
    │           │            │
┌───▼───────────▼────────────▼──────────────────────────────────────────────────┐
│                             INFRASTRUCTURE TIER                                │
│ ┌────────────┐ ┌─────────────┐ ┌──────────┐ ┌─────────┐ ┌──────────────────┐ │
│ │ PostgreSQL │ │   Qdrant    │ │  Redis   │ │ Object  │ │ Ollama GPU Pool  │ │
│ │ +pgvector  │ │  vector DB  │ │ cache +  │ │ store   │ │ (load-balanced)  │ │
│ │ metadata,  │ │ per-space   │ │ queue    │ │ PDFs    │ │ chat/embed/rerank│ │
│ │ chat, notes│ │ collections │ │ (Celery) │ │ (MinIO) │ │ /verify models   │ │
│ └────────────┘ └─────────────┘ └──────────┘ └─────────┘ └──────────────────┘ │
│ ┌───────────────────────────┐ ┌────────────────────────────────────────────┐ │
│ │ GROBID / PDF parser svc   │ │ Langfuse (self-hosted tracing & eval)      │ │
│ └───────────────────────────┘ └────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────────────────────────────┘
```

### 3.1 Container Responsibilities

| Container | Responsibility | Scaling |
|---|---|---|
| Frontend | UI, streaming render, citation highlighting | CDN/static, trivial |
| API Gateway | Auth, validation, tenancy, streaming transport | Horizontal, stateless |
| Orchestrator | Agent graph execution, state, routing | Horizontal, stateless (state in Postgres) |
| Ingestion workers | PDF fetch/parse/chunk/embed | Horizontal, queue-depth autoscale |
| PDF parser service | GROBID layout-aware extraction | Horizontal, CPU-bound |
| Ollama pool | All model inference | Vertical (GPU) + horizontal replicas |
| PostgreSQL | Relational truth: spaces, papers, turns, notes, verification trails | Primary + read replicas |
| Qdrant | Chunk embeddings, per-space collections | Sharded cluster |
| Redis | Cache (API responses, embeddings, answers) + Celery broker | Cluster mode |
| MinIO | Raw PDFs and exports | Horizontal |
| Langfuse | Traces, evals, prompt versions | Single instance |

---

## 4. Agent Architecture (C4 Level 3)

### 4.1 Agent Catalogue

| Agent | Input | Output | Model profile | Runs in |
|---|---|---|---|---|
| **Supervisor** | User turn + space state | Route decision | small, temp 0 | Orchestrator |
| **Query Planner** | Raw user intent | Structured search plan, sub-queries, filters | small, temp 0.2 | Discovery flow |
| **Discovery** | Search plan | Normalised, deduped candidate papers | none (deterministic I/O) | Async fan-out |
| **Ranking/Rerank** | Candidates + intent | Semantically ordered list + scores | embedding + cross-encoder | GPU |
| **Ingestion** | Paper ref or upload | Chunks + embeddings + structured metadata | embedding | Worker |
| **Retrieval** | Question + space scope | Top-K evidence chunks with provenance | embedding + reranker | GPU |
| **Answer (Generator)** | Question + evidence | Draft answer + per-claim citation map | medium/large, temp ≤ 0.3 | GPU |
| **Peer Reviewer (Critic)** | Question + evidence + draft | Claim-level verdicts + corrections + score | large (or distinct model), temp 0 | GPU |
| **Refinement Controller** | Reviewer verdict + history | Accept / regenerate / re-retrieve / abstain | deterministic code | Orchestrator |
| **Compare/Gap** | N paper profiles | Comparison matrix, commonalities, contradictions, gaps | large | GPU |
| **Notes** | Paper chunks | Structured note document | medium | GPU |
| **Memory** | Turn history | Rolling summary + salient-fact store | small | Async |

### 4.2 Orchestration Pattern

**Supervisor + specialised workers, expressed as an explicit LangGraph state machine.**
Chosen over free-form agent chatter because:

- deterministic, auditable routing is required for the accuracy gate,
- cycles are first-class (the verification loop *is* a cycle),
- state is checkpointable, enabling resume and full trace replay,
- failure modes are bounded and testable per node.

Shared graph state object (conceptual):

```
TurnState {
  space_id, turn_id, user_query, intent,
  search_plan, candidates[], evidence_chunks[],
  draft_answer, claim_map[],
  review_history[], iteration, score,
  final_answer, confidence, action_log[]
}
```

### 4.3 Phase 3 Verification Loop — Detailed Design

```
 ┌──────────────┐
 │  RETRIEVE    │◄──────────────────────────────────────────┐
 │ hybrid+rerank│                                           │
 └──────┬───────┘                                           │
        ▼                                                   │
 ┌──────────────┐        feedback_history[]                 │ expanded
 │  GENERATE    │◄────────────────────────────┐             │ queries
 │ draft+claims │                             │             │
 └──────┬───────┘                             │             │
        ▼                                     │             │
 ┌──────────────────────────┐                 │             │
 │  PEER REVIEW (critic)    │                 │             │
 │  independent, temp 0     │                 │             │
 │  claim-by-claim entail-  │                 │             │
 │  ment check vs evidence  │                 │             │
 └──────┬───────────────────┘                 │             │
        ▼                                     │             │
 ┌──────────────────────────┐                 │             │
 │  REFINEMENT CONTROLLER   │                 │             │
 │  score ≥ 0.90 & no       │                 │             │
 │  UNSUPPORTED/CONTRA/     │                 │             │
 │  MISCITED ?              │                 │             │
 └──┬────────┬──────────┬───┘                 │             │
    │ yes    │ REVISE   │ EVIDENCE_GAP        │             │
    │        └──────────┼─────────────────────┘             │
    │                   └───────────────────────────────────┘
    ▼
 ┌──────────────────────────────────────────┐
 │ FINALISE: answer + citations +           │
 │ confidence + verification trail          │
 └──────────────────────────────────────────┘

 Guards: max 3 iterations · 20 s wall clock · oscillation detection
 Exhaustion: return best draft, flag unverified claims, low-confidence banner
```

**Why a separate reviewer rather than self-critique:** self-critique inherits the generator's
errors (correlated failure). Independence is enforced by (a) a different prompt with no access to
the generator's chain of thought, (b) temperature 0, (c) optionally a different model family,
(d) a strict JSON verdict contract that forces per-claim evidence quoting rather than a holistic
opinion.

**Cost/latency control:** loop only runs for grounded-answer flows; approved-first-pass turns
incur exactly one extra reviewer call (~1–2 s); the p50 iteration count target is ≤ 1.6.

### 4.4 Retrieval Pipeline

```
question
   │
   ├─► query rewrite (context-aware, resolves "it"/"that paper")
   ├─► sub-query decomposition for multi-hop questions
   │
   ├──────────────┬──────────────────┐
   ▼              ▼                  ▼
 dense search   BM25 sparse     metadata filter
 (Qdrant,       (Postgres FTS)  (space scope,
  top 50)        (top 50)        paper subset)
   └──────────────┴──────────────────┘
                  ▼
        Reciprocal Rank Fusion
                  ▼
        Cross-encoder rerank (GPU) → top K (8–12)
                  ▼
        Context assembly: dedupe, diversity (MMR),
        token-budget packing, provenance attached
                  ▼
        Evidence set → Answer Agent
```

Hybrid + rerank is the single largest lever on retrieval recall (NFR-2.4) and therefore on
downstream answer accuracy.

---

## 5. Data Architecture

### 5.1 Logical Model

```
User ──1:N── ResearchSpace ──1:N── Turn ──1:N── VerificationIteration
                 │                   │
                 │                   └──1:N── Citation ──N:1── Chunk
                 ├──M:N── Paper ──1:N── Chunk ──1:1── Embedding(Qdrant)
                 │           │
                 │           ├──1:1── PaperProfile (structured extraction)
                 │           └──1:N── Note
                 ├──1:N── ComparisonReport
                 └──1:1── SpaceMemory (rolling summary + findings)
```

### 5.2 Storage Allocation

| Data | Store | Rationale |
|---|---|---|
| Spaces, papers, turns, notes, verification trails | PostgreSQL | Relational integrity, transactional, queryable |
| Chunk embeddings | Qdrant (collection per space, or shared with `space_id` filter) | Fast filtered ANN at scale |
| Sparse/keyword index | Postgres full-text (or OpenSearch at scale) | Hybrid retrieval second leg |
| Raw PDFs, exports | MinIO/S3 | Large binary, cheap |
| API response cache, embedding cache, answer cache | Redis | Latency |
| Job queue | Redis + Celery | Async ingestion |
| Traces, evals, prompts | Langfuse | Observability + accuracy measurement |

### 5.3 Canonical `Paper` Model

Every source adapter normalises into one shape: `doi, arxiv_id, pmid, openalex_id, title,
authors[], year, venue, abstract, citation_count, oa_status, pdf_url, source, raw_payload`.
Deduplication precedence: DOI → arXiv ID → PMID → normalised-title + first-author + year fuzzy match.

---

## 6. Cross-Cutting Concerns

### 6.1 Latency Strategy

| Technique | Applied where |
|---|---|
| Parallel fan-out | 6 scholarly APIs queried concurrently with per-source timeout (2.5 s) |
| Multi-tier cache | search results (TTL 24 h), embeddings (permanent), paper profiles (until re-ingest), answers (per space+question hash) |
| Streaming | token streaming for the *approved* answer; draft generation hidden behind a "verifying" indicator |
| Model tiering | small model for routing/rewrite/memory; medium for answers; large only for review escalation and gap synthesis |
| Precomputation | paper profiles and notes generated at ingest time, not query time |
| Bounded loop | hard iteration and wall-clock caps make worst case deterministic |

### 6.2 Accuracy Strategy (defence in depth)

1. **Retrieval quality** — hybrid + RRF + cross-encoder rerank + MMR diversity.
2. **Generation discipline** — evidence-only prompt, mandatory per-claim citation, low temperature, explicit abstention instruction.
3. **Independent review** — peer reviewer claim-level entailment check.
4. **Iterative repair** — targeted regeneration with reviewer corrections, or re-retrieval on evidence gaps.
5. **Honest degradation** — flag or strip unverified claims; never return silent hallucination.
6. **Continuous measurement** — gold-set evaluation harness in CI; regression gate on merge.

### 6.3 Security

- Egress allow-list enforced at the network layer; violation alarms.
- Prompt-injection defence: retrieved document text wrapped in delimited, clearly-labelled
  untrusted blocks; instruction-like content in PDFs neutralised; agents forbidden from
  following instructions found in evidence.
- Tool calls validated against JSON schemas; no arbitrary code/shell tool exposed to agents.
- Row-level tenant filters applied in the repository layer, not in agent prompts.
- Uploaded PDFs scanned and parsed in a sandboxed worker.

### 6.4 Failure Modes & Mitigations

| Failure | Mitigation |
|---|---|
| External source down/rate-limited | Circuit breaker, cached results, partial-result response with source-health badge |
| Ollama unavailable | Health-check gate, queued retry, clear UI error; no cloud fallback (privacy) |
| PDF unparseable | OCR fallback → abstract-only mode with reduced-coverage label |
| Loop oscillation | Convergence guard (LC-5), early stop |
| Loop budget exhausted | Best-effort answer, unverified claims flagged, low-confidence banner |
| Reviewer over-strict (false rejection) | Approval-rate monitoring, threshold tuning, human-audited sample |
| Vector store hot shard | Per-space collections, shard rebalancing |
| Context overflow in long chats | Hierarchical memory: recent verbatim + rolling summary + vector recall |

---

## 7. Technology Decisions (ADR summary)

| # | Decision | Alternatives considered | Rationale |
|---|---|---|---|
| ADR-01 | **LangGraph** for orchestration | CrewAI, AutoGen, custom | Explicit cyclic state machine required for the verification loop; auditability; checkpointing |
| ADR-02 | **Ollama** self-hosted for all inference | Cloud APIs, vLLM, TGI | Hard privacy requirement; simple model management; vLLM remains a swap-in behind the provider interface if throughput demands it |
| ADR-03 | **Qdrant** as vector store | pgvector, Weaviate, Milvus, Chroma | Filtered ANN at 10M+ scale, native multi-tenancy, self-hostable; pgvector acceptable for single-user deployments |
| ADR-04 | **PostgreSQL** as system of record | MongoDB | Relational integrity across space/paper/turn/citation; strong FTS for hybrid retrieval |
| ADR-05 | **Hybrid retrieval + cross-encoder rerank** | Dense-only | Materially higher recall/precision on technical text; directly serves NFR-2 |
| ADR-06 | **Separate reviewer agent** rather than self-critique | Self-reflection, single-pass CoT | Avoids correlated errors; enables objective claim-level verdicts and a measurable gate |
| ADR-07 | **Celery + Redis** for async ingestion | In-process background tasks | Keeps chat latency isolated from heavy ingest; independent autoscaling |
| ADR-08 | **GROBID** for scholarly PDF parsing | Naive text extraction | Section/reference structure is essential for precise, page-anchored citations |
| ADR-09 | **Source-adapter pattern** | Direct API calls in agent code | Six heterogeneous sources; enables per-source circuit breaking and easy addition of new sources |
| ADR-10 | **Prompts externalised + versioned** | Inline strings | Prompts are the primary accuracy lever; must be diffable, A/B-testable and rollback-able |

---

## 8. Deployment Architecture

```
                         ┌──────────────┐
                         │  Ingress /   │  TLS termination
                         │  Reverse LB  │
                         └──────┬───────┘
          ┌─────────────────────┼─────────────────────┐
          ▼                     ▼                     ▼
   ┌────────────┐        ┌────────────┐        ┌────────────┐
   │ frontend   │        │ api (N)    │        │ langfuse   │
   │ (static)   │        │ stateless  │        │            │
   └────────────┘        └─────┬──────┘        └────────────┘
                               │
                    ┌──────────▼──────────┐
                    │ orchestrator (N)    │ stateless, CPU
                    └──────────┬──────────┘
                               │
        ┌──────────────┬───────┴────────┬──────────────────┐
        ▼              ▼                ▼                  ▼
 ┌────────────┐ ┌────────────┐  ┌──────────────┐   ┌──────────────┐
 │ worker (M) │ │ grobid (K) │  │ ollama pool  │   │ data tier    │
 │ CPU, queue │ │ CPU        │  │ GPU nodes,   │   │ postgres     │
 │ autoscaled │ │            │  │ LB'd, warm   │   │ qdrant redis │
 └────────────┘ └────────────┘  │ model cache  │   │ minio        │
                                └──────────────┘   └──────────────┘

Dev:  docker compose up   (all of the above, single GPU host)
Prod: Kubernetes — HPA on api/orchestrator/worker; GPU node pool for ollama;
      StatefulSets for postgres/qdrant/minio.
```

**Model placement guidance (single-GPU starting point):**
chat/answer model ~7–8B quantised, reviewer model 7–14B (distinct family), embedding model
small (`nomic-embed-text` / `mxbai-embed-large`), reranker `bge-reranker-v2-m3`. Keep models
resident (`OLLAMA_KEEP_ALIVE`) to avoid cold-load latency; set `OLLAMA_NUM_PARALLEL` for
concurrent request handling.

---

## 9. Evaluation & Quality Subsystem

Treated as a product component, not a test afterthought:

- **Gold set:** curated questions per paper corpus with reference answers and reference passages.
- **Metrics:** retrieval recall@k / nDCG, groundedness, citation precision, answer correctness
  (LLM-judge + human audit), abstention correctness, loop iteration statistics, latency percentiles.
- **CI gate:** regression run on every prompt or retrieval change; merge blocked on metric regression.
- **Live monitoring:** reviewer approval rates, budget-exhaustion rate, per-space confidence
  distribution surfaced on an ops dashboard.

---

## 10. Phase Roadmap Mapping

| Phase | Delivers | Architectural additions |
|---|---|---|
| **P1 — MVP** | Discovery (arXiv, S2, OpenAlex), ingest, basic RAG Q&A, persistent chat | API, orchestrator, Qdrant, Postgres, Ollama, ingestion worker |
| **P2 — Depth** | All 6 sources, pinning, notes, compare/gap, paper profiles, exact-paper lookup | Compare agent, notes agent, GROBID, profile extraction, memory summarisation |
| **P3 — Accuracy loop** | Peer-review verification loop, hybrid+rerank retrieval, verification trail UI, confidence scores | Reviewer agent, refinement controller, cross-encoder, RRF fusion, claim mapping, eval harness |
| **P4 — Scale & ops** | Multi-user tenancy, K8s + GPU autoscaling, eval dashboard, exports | HPA, sharding, Langfuse dashboards, RBAC |

---

## 11. Key Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Local models weaker than frontier models on synthesis | Accuracy target missed | Loop compensates; reserve larger model for review/synthesis; allow model upgrade behind the provider interface |
| Verification loop inflates latency | NFR-1 breach | Bounded iterations, wall-clock cap, streaming UX, first-pass approval-rate tuning |
| Paywalled papers limit full-text coverage | Reduced answer quality | OA-first strategy, user upload path, explicit coverage labelling |
| External API terms/rate limits | Discovery degradation | Caching, polite pooling, circuit breakers, per-source keys |
| GPU capacity under concurrency | Queueing | Model tiering, keep-alive, horizontal GPU pool, request admission control |
| Prompt injection via malicious PDF | Integrity/security | Delimited untrusted blocks, instruction-ignoring policy, tool allow-list |
