# 11. Low Level Design

The user-facing product is **R.Space**; this document retains historical
component names and the existing repository/database/API identifiers.

## Table of contents

1. Module breakdown
2. Verification loop internals
3. Retrieval pipeline internals
4. Source adapters and discovery internals
5. Ingestion internals
6. Annotations and paper reader internals
7. Database schema
8. REST API reference
9. Error handling and degradation matrix
10. Testing strategy
11. Performance optimizations
12. Design vs. implementation notes

## 1. Module breakdown

### 1.1 Application startup and configuration

| Symbol | Signature or shape | Responsibility |
|---|---|---|
| `create_app` | `def create_app() -> FastAPI` in `app\main.py` | Builds the FastAPI app, adds CORS, and mounts `/v1` routes. |
| `lifespan` | `async def lifespan(app: FastAPI)` | Refuses an outdated Alembic revision, prepares the one-time local setup token, rehydrates owned embeddings, and closes Ollama on shutdown. |
| `Settings` | `class Settings(BaseSettings)` in `core\config.py` | Loads database, Ollama, source, web, and loop settings from `.env`. |
| `configure_sqlite_pragmas` | `def configure_sqlite_pragmas(async_engine)` | Registers SQLAlchemy connect hook for `foreign_keys=ON`, WAL, and `busy_timeout=5000`. |
| `scripts.migrate` | `python -m scripts.migrate` | Takes a consistent retained SQLite backup and runs validated Alembic revisions before startup. |

### 1.2 API modules

| File | Functions |
|---|---|
| `api\v1\health.py` | `health`, `models` |
| `api\v1\auth.py` | Bootstrap, login, logout, logout-all, administrator user creation/password reset, per-user OpenAlex consent read/update; cookie-authenticated and CSRF-protected. |
| `api\v1\linkedin.py` | Optional connection status, OAuth state-bound connect/callback/disconnect, owner-checked single-item text post with explicit visibility and one-use request ID. |
| `api\v1\spaces.py` | `create_space`, `list_spaces`, `get_space`, `rename_space`, `archive_space`, `unarchive_space`, `duplicate_space`, `delete_space`, `search_content`, `list_turns` |
| `api\v1\search.py` | `search_tags`, `search`, `source_adapters` |
| `api\v1\papers.py` | `pin_paper`, `capture_web`, `get_paper`, `paper_content`, `paper_status`, `unpin` |
| `api\v1\chat.py` | `chat` |
| `api\v1\compare.py` | `compare`, `list_comparisons`, `get_comparison` |
| `api\v1\notes.py` | `create_note`, `auto_note`, `list_notes`, `paper_annotations`, `get_note`, `update_note`, `delete_note`, `get_memory` |
| `api\v1\verification.py` | `verification_trail` |

`SourceRegistry.fan_out` checks the owner-scoped `SourceResultCache` after
constructing each adapter's exact query. A hit supplies a fresh deserialized
copy of its `RawPaperRecord` list and reports `SourceHealth.cached`; the
discovery service still normalizes, deduplicates and ranks on every request.
Only fully successful adapter responses are cached. HTTP errors, rate
limits and hard deadlines stay degraded and are retried on the next search.
The 15-minute LRU is capped at 256 entries and 32 MiB and cleared on
shutdown. No Redis or public cache access is involved.

### 1.3 Services and agents

| Component | Main public methods | Notes |
|---|---|---|
| `DiscoveryService` | `discover(self, topic, filters=None)` | Plans, fans out, normalizes, deduplicates, ranks, and partitions web results. |
| `PaperService` | `pin_and_ingest`, `capture_web`, `get`, `get_status`, `unpin` | Handles persistence, SSRF-safe fetches, parsing, chunking, embedding, and vector registration. |
| `PdfUploadService` | `ingest(space_id, uploaded, title)` | Streams owner-authenticated multipart PDFs to private storage, reuses the existing owner/content hash, parses pages, persists embeddings and pins, and reports scanned-PDF degradation. |
| `QAOrchestrator` | `answer(self, space_id, question)` | Builds memory, rewrites queries, retrieves evidence, runs verification, persists turns and trails. |
| `CompareService` | `compare`, `list_reports`, `get_report` | Validates pins, builds profiles, generates matrix and gaps, verifies conclusions, caches reports. |
| `NoteService` | `auto_generate`, `create`, `update`, `delete`, `list`, `annotations`, `augment_evidence_with_notes` | Implements notebook, auto notes, reader annotations, and note evidence chunks. |
| `QueryPlanner.plan` | `async def plan(self, topic: str, filters: SearchFilters | None = None, include_web: bool = False, domain_tags: list[str] | None = None, limit: int = 20) -> SearchPlan` | Parses tags and creates source hints. |
| `RankingAgent.rank` | `async def rank(self, papers, topic: str, domain_tags: list[str] | None = None)` | Keyword overlap, citation count, OA bonus, domain boost, and web penalty. |
| `AnswerAgent.generate` | `async def generate(self, question: str, evidence: EvidenceSet, feedback_history=None) -> Draft` | Uses Ollama medium model at temperature 0.3 and extracts bracket citations into claims. |
| `PeerReviewerAgent.review` | `async def review(self, question, evidence, draft, iteration: int = 1) -> ReviewVerdict` | Uses verify model at temperature 0.0 and large model on iteration 3 or later. |

Model-output JSON normalization is shared by Compare, Gap, Notes, Memory,
Profile, Verdict and optional JSON-formatted query rewrites. It tolerates
case variants, fenced JSON/trailing commas, singular or plural list keys,
common list wrappers, and a bare string only where the receiving field is
explicitly a text field. This normalizes **shape, not content**: an omitted
claim status, citation ID, dimension, or substantive value is never invented.
Tests include the captured `P1`/`P2`/`commonality` response that originally
failed Compare parsing and the measured `datasets` string-list shape. JSON
decoding of Ollama's streaming HTTP protocol is separate transport parsing,
not a model-output schema.

The audit found **seven** model-output consumers: Compare (flat label maps,
singular findings), Gap (list wrappers and bare text), Notes (contribution
strings/objects), Memory (finding/question lists), Profile (wrapped fields),
Verdict (fences, casing and explicit claim status), and QueryRewriter
(optional JSON answer). A `datasets` array is not a current product parser:
its observed bare-string response is tested against the shared shape helper,
not interpreted as verified dataset entities. Ollama streaming uses JSON
for response framing only. A malformed reviewer claim without its own
`claim_id` and `status` is rejected instead of inventing support.

## 2. Verification loop internals

### 2.1 Data structures

`schemas\chat.py` defines `ScoredChunk`, `EvidenceSet`, `ConversationContext`, `Claim`, `Draft`, `CitationDTO`, `TurnState`, and `AnsweredTurn`. `TurnState` exists as a Pydantic model but the delivered driver does not use a LangGraph state machine. Runtime state is local variables in `VerificationLoopDriver.run`.

`schemas\verification.py` defines `ClaimStatus` values SUPPORTED, PARTIAL, UNSUPPORTED, CONTRADICTED, MISCITED; `VerdictType` values APPROVED, REVISE, EVIDENCE_GAP, REJECT; `LoopAction` values ACCEPT, REGENERATE, RE_RETRIEVE, ABSTAIN, FINALIZE_BEST_EFFORT; plus `ClaimFinding`, `ReviewVerdict`, and `LoopTrace`.

### 2.2 Loop driver

`VerificationLoopDriver(retriever, answer_agent, reviewer_agent, controller, trail=None, embedder=None)` exposes `async def run(self, space_id: str, question: str, turn_id: str | None = None, extra_queries: list[str] | None = None)`.

Algorithm:

1. Allocate `turn_id`.
2. Retrieve initial evidence inside `asyncio.timeout(self._remaining_seconds(start))`.
3. Generate a draft with `AnswerAgent.generate(question, evidence, history)`.
4. Review with `PeerReviewerAgent.review(question, evidence, draft, iteration)`.
5. Resolve citation IDs, then embed the claim and overlapping evidence windows in one batch (five-second maximum); use the highest-scoring passage both for deterministic grounding and the final citation excerpt. Missing/unavailable embeddings fall back to the original first-200-character excerpt and reviewer judgment with a logged warning.
6. Keep the draft with the most supported cited claims (then highest reviewer score), together with its original evidence and matching excerpts.
7. Ask `RefinementController.decide` for the next action.
8. Persist traces on terminal action.
9. Return `_answered`, `_finalize_best_effort`, or `_abstain`.

### 2.3 Acceptance rules and citation validation

`LoopPolicies.is_acceptable` requires threshold score, verdict APPROVED, no UNSUPPORTED, CONTRADICTED, or MISCITED claims, and reviewer coverage for every draft claim. `prepare_verdict` aligns reviewer findings to draft claims only by `claim_id`; missing or mismatched reviewer IDs force REVISE with UNSUPPORTED findings. Matching counts alone cannot establish claim identity.

`LoopPolicies._resolve_cited_id` checks each cited chunk against current evidence. It repairs only recognizable shorthand such as `chunk1`, `chunk-1`, `c1`, numeric position, or a unique substring. Arbitrary fabricated IDs become MISCITED.

Claims without citations are UNSUPPORTED. An existing cited chunk is MISCITED when its best claim-to-passage cosine is below **0.65**, even if the reviewer approves it; *every* cited chunk must pass. This threshold separates the observed .70-.80 faithful passages from .33-.55 unrelated passages, but semantic similarity is not entailment: an embedding can still favor a relevant-looking false claim. Do not treat a passing score alone as verification. Citation excerpts use roughly 500-character, half-overlapping windows snapped opportunistically to sentence boundaries; the previous first-200-character excerpt remains a candidate. Each resulting `CitationDTO` carries the original claim text and measured score, and `0006_citation_match_score` adds a nullable `citations.match_score` column for new rows. Existing rows are not backfilled.

For an explicitly shared/same/both/similarity question retrieved from multiple papers, each accepted shared finding must cite passages from **at least two distinct papers**. If the model only cites one paper, the claim is MISCITED even when the passage has high cosine. An unapproved shared-finding draft abstains rather than returning a tempting but unsupported best-effort comparison. Reviewer output that does not cover every draft claim yields UNSUPPORTED findings, never unreviewed "supported" findings that could survive best-effort. These checks address attribution and omission, not logical entailment or a named entity's type; jointly cited but false synthesis remains a known limitation.

### 2.4 ConvergenceGuard and LC mapping

The implemented guard is `Convergence(min_improvement=0.05)`. `has_stalled(history)` returns true after three verdicts if both recent score gains are below 0.05. `has_ungrounded_stall` stops after two verdicts without supported cited claims and less than 0.05 score improvement, avoiding a third expensive synthesis attempt.

| Rule | Code mapping | Notes |
|---|---|---|
| LC-1 Iteration budget | `LoopPolicies.max_iterations`, checked in `decide`. | Configured by `LOOP_MAX_ITERATIONS`. |
| LC-2 Acceptance threshold | `is_acceptable`. | Needs score, APPROVED, and no bad claims. |
| LC-3 Routing | `LoopPolicies.decide`. | UNSUPPORTED re-retrieves; PARTIAL, MISCITED, CONTRADICTED, or REVISE regenerates; REJECT abstains. |
| LC-4 Feedback carry-forward | `history` passed to `AnswerAgent.generate`. | Prompt receives prior verdicts. |
| LC-5 Convergence guard | `Convergence.has_stalled` and `has_ungrounded_stall`. | Stops with FINALIZE_BEST_EFFORT. |
| LC-6 Exhaustion behavior | `_finalize_best_effort`. | Keeps SUPPORTED and PARTIAL claims only. |
| LC-7 Abstention | `_abstain`. | Returns `Not answerable from the attached papers.` |
| LC-8 Independence | Separate answer and reviewer prompts/models. | Reviewer temperature is 0.0. |
| LC-9 Determinism | Agent temperatures in code. | Generator 0.3, reviewer 0.0. |
| LC-10 Auditability | `VerificationTrail.persist` plus `verification_iterations`. | UI displays trail. |
| LC-11 Latency guard | `asyncio.timeout(self._remaining_seconds(start))`. | Uses `LOOP_WALL_CLOCK_CAP_MS`. |
| LC-12 Escalation | `PeerReviewerAgent.review` uses large model when `iteration >= 3`. | Final adjudication path. |

### 2.5 Finalizers, timeout, and persistence

`_answered` builds claim-specific `CitationDTO` entries from surviving claims and evidence metadata (the same chunk may support two different claims). The UI resolves repeated chunk markers by their occurrence in the answer and displays the corresponding cited claim next to its excerpt. `_finalize_best_effort` keeps only cited SUPPORTED and PARTIAL claims, flags low confidence, or abstains when no cited claims survive; unapproved shared-finding answers always abstain. `_abstain` returns a non-answer, optional evidence titles, and suggests narrowing the question.

Initial retrieval failures return an abstention with a synthetic REVISE verdict. Failures after a best draft exists return best-effort with warning. `LLMUnavailableError` is raised by `OllamaClient.chat`, `chat_stream`, and `embed` wrappers.

`QAOrchestrator.answer` writes user and assistant turns, non-note citations (actual claim text, selected quote, nullable similarity), and all loop traces to `verification_iterations`. Each generated/reviewed trace records both model names in `model_used`. Deploy the new nullable-column migration on a backed-up database *before* starting code from this branch; startup fails closed on the older `0005` schema.

Revision `0007_chat_sessions` adds `chat_sessions` plus nullable `turns.session_id`/`turns.mentions`, and groups each space's existing turns into one session titled from its first question. Turns whose space row is missing are left without a session so no foreign-key violation is introduced. Chat questions are answered within a session: query rewriting sees only that session's recent turns (plus any @-mentioned sessions' summary or last turns); the answer prompt stays evidence-only. Compression summarises all but the newest four turns in batches with `MemoryAgent.summarize` and reuses a still-valid earlier summary incrementally.

When comparing rows across migration backups, derive ordering columns from each table's `PRAGMA table_info` primary-key ordinal, not an assumed `id` column: `auth_sessions.token_hash`, `openalex_consents.user_id`, and `space_memory.space_id` are non-`id` keys. A `0005` to `0006` live preflight once stopped safely after assuming `auth_sessions.id`; the corrected primary-key-aware check passed on both the backup rehearsal and live database before migration.

## 3. Retrieval pipeline internals

`QueryRewriter.rewrite(question, conversation_context)` only rewrites when referential terms are present. It uses the last two recent turns, each truncated to 200 characters, and returns `[standalone, original]` when the rewrite differs. This replaced a failed naive approach where embedding a full memory blob biased retrieval toward stale topics.

`HybridRetriever.retrieve(space_id, question, scope=None, extra_queries=None)` builds a unique query list. Dense search embeds each query with Ollama `nomic-embed-text` and searches `InMemoryVectorStore` top 50. Sparse search scores chunks with TF-IDF-like term frequency and inverse document frequency. `ReciprocalRankFusion` combines rankings; `Reranker` adds lexical overlap; `MMR` selects diverse top 8 chunks; `ContextBuilder.pack(word_budget=1800, max_chunks=8)` produces the evidence set. The conservative budget prevents Ollama context overflow and empty drafts.

`NotesAwareRetriever` appends up to three relevant note chunks after paper evidence. Note chunks have IDs like `note-{note_id}` and are returned to the model but not inserted into `citations` rows because they have no chunk foreign key.

## 4. Source adapters and discovery internals

`SourceAdapter` declares `name`, `search(SearchQuery)`, `fetch_by_id(PaperIdentifier)`, `resolve_fulltext(RawPaperRecord)`, and `health_check`. Only `search` is implemented by live adapters.

| Adapter | Implementation detail |
|---|---|
| `ArxivAdapter` | Atom API; adds `cat:` fragments from domain tags; captures categories and PDF link. |
| `OpenAlexAdapter` | Works API; normalizes DOI, returns citation count, OA status, and PDF URL. |
| `CrossrefAdapter` | Works API; extracts title, authors, year, DOI, venue, citation count, JATS abstract, and candidate HTTPS PDF links intended for text mining/similarity checking. `vor` is not taken as proof of open access. |
| `PubMedAdapter` | NCBI `esearch` then `esummary`; optional API key; returns PMID, DOI, authors, journal, and year. |
| `SemanticScholarAdapter` | Graph API; requires `SEMANTIC_SCHOLAR_API_KEY` to avoid unauthenticated rate limits. |
| `COREAdapter` | CORE v3; returns empty list unless `CORE_API_KEY` is configured. |
| `WebSearchAdapter` | Selected web provider; caps to 8 results; returns source `web` records with URL and snippets. |

`SourceRegistry.fan_out` wraps each adapter in a `CircuitBreaker` and `asyncio.timeout(settings.source_timeout_s)`. This is needed because httpx operation timeouts do not guarantee a whole-call deadline for slow trickle responses.

`sources\taxonomy.py` defines tags such as `ml`, `nlp`, `medical`, `bio`, `physics`, `math`, `security`, `systems`, `climate`, and `econ`. `parse_tags` strips known tags and `plan_for_tags` derives source priority, arXiv categories, and query terms.

`Deduplicator.merge` uses DOI, arXiv, and PMID indexes first, then fuzzy title matching only after cheap gates: length, year, first-author surname, and token overlap. This changed the hot path from broad O(n squared) fuzzy comparisons to about 2 ms for typical batches.

## 5. Ingestion internals

`validate_public_https_url(url)` rejects missing host, non-HTTPS scheme, loopback, private, link-local, multicast, reserved, unspecified, and invalid IPs. `PaperService` validates the original PDF URL and each redirect before requesting it.

Limits and parsing:

- `MAX_PDF_BYTES = 30 * 1024 * 1024`.
- Multipart requests have a streaming ASGI receive cap of 30 MiB plus 1 MiB for form overhead; the PDF part itself has a strict 30 MiB streaming cap. Files are spooled and never read unbounded from the request.
- `MAX_PDF_PAGES = 300`.
- `MAX_WEB_CAPTURE_BYTES = 5 * 1024 * 1024`.
- PDFs must start with `%PDF-`.
- Full web capture checks robots.txt and supports HTML or PDF; selected-content capture skips network fetch.
- `_parse_pdf_pages(data)` uses `pypdf.PdfReader`.
- `_chunk_pages(pages, size=350, overlap=50)` segments PDF text on original line-break headings **before** flattening words. A numbered outline begins with a `1 Introduction`/`1 Method` anchor; without one, numbered table rows and bibliography entries are not treated as headings. Exact unnumbered headings such as `ABSTRACT` can still be used. Canonical labels (`Method`, `Results`, `Dataset`, etc.) prefix the preserved raw heading when an unambiguous mapping exists. If no real heading applies, the section is `None` (rendered "Unknown"); no previous heuristic label is inherited on a new page. Neither chunks nor citation passages span a page. Abstract-only and web-capture text bypass heading detection.

`OllamaClient.embed` posts to `/api/embed` in batches of 32. `_validate_vectors` requires matching vector count, non-empty vectors, and one shared vector dimension. If validation fails, chunks are not partially published.

`_upsert_paper_row` dedupes by canonical DOI, canonical arXiv ID, content hash, or web URL, and fills missing abstracts/PDF candidates on a re-pin without overwriting existing metadata. The metadata parser strips JATS/HTML markup and collapses whitespace in title/abstract fields; the cross-source author merge prefers a full name over a unique same-position surname/initial variant while keeping ambiguous names distinct. `_load_chunks` reuses existing chunks and embeddings. `pin_and_ingest` checks the pin still exists before and after chunk persistence so an unpin during ingest does not publish stale chunks. `pin_and_ingest_background` (used by the Library via `?background=true`) commits the paper row and pin first, returns immediately, and runs the same ingest in a background task bounded to two concurrent ingests per event loop; clients poll `/papers/{paper_id}/status`. Tasks still running at shutdown leave the paper `QUEUED`/in progress and can be re-pinned.

Heading-aware chunking affects **new ingestion only**. Existing persisted
chunks and historical citation rows retain old labels. Do not delete and
recreate papers or chunks to correct those labels: IDs are referenced by
pins, notes and citations. A safe future backfill requires an approved
WAL-consistent backup, the same source PDF bytes (all old page tokens must
align uniquely), a section-only update to existing `chunks` and matching
`citations` rows in one transaction, and identity/FK/integrity checks.
If an old chunk spans two detected sections, set its section to unknown
instead of guessing. Rehydrate in-process vector metadata after any
approved update. The disposable rehearsal in
`backend/evaluations/document_structure/heading-coverage.json` updated
word2vec's section values in place while preserving all 27 chunk IDs
and a synthetic citation link; it **skipped** GloVe because only 17 of
33 old chunks aligned to the available PDF variant. No live backfill was
performed.

Statuses are QUEUED, FETCHING, PARSING, CHUNKING, EMBEDDING, PROFILING, READY, FAILED, and DEGRADED. Publisher links can require authentication; HTML/login pages, 401/403 responses, oversized downloads and non-PDF bytes cannot be ingested as paper text. An abstract-only ingest has readable chunks but stays DEGRADED; missing accessible PDF and abstract stays DEGRADED with no chunks. Exceptions mark FAILED. Unpaywall remains a stub pending separate consent for its required contact email.

For local uploads, `UPLOAD_DIR` defaults to `%LOCALAPPDATA%\R.Space\uploads` on
Windows and must resolve outside the repository. The owner directory is a
SHA-256 digest of the authenticated ID; filenames are generated from the
persisted paper ID, not the client filename. A PDF must begin with `%PDF-`,
parse as a PDF, and contain at most 300 pages. Parsed pages use the same
section-aware chunker and configured local Ollama embeddings as fetched
papers. A text-free scan is stored/pinned as `DEGRADED` without chunks, not
claimed citable. The original file is served only by the authenticated,
owner-checked `/v1/papers/{paper_id}/file` route; no filesystem path is sent to
the browser. Source-cache keys and Google Scholar behavior are unaffected.

## 6. Annotations and paper reader internals

The delivered `notes` table includes `chunk_id`, `anchor_quote`, `anchor_start`, `anchor_end`, and `color`. The Alembic legacy baseline adds missing annotation/citation columns after validating the old schema; revision `0004_note_chunk_fk` conditionally restores the FK omitted by the historical startup `ALTER TABLE`. Existing note rows and broken references are preserved, including one previously unenforced note-to-chunk orphan in the local legacy DB. Application startup never changes schema.

The React `PaperReader` computes offsets with `textOffset(root, node, offset)` against the paragraph marked `data-chunk-body`, not the enclosing section. This avoids counting the section/page label and shifting anchors.

`ReaderChunk` sorts anchored notes by `anchor_start`, clips each range against the current cursor, and renders the visible remainder as a clickable highlight. Fully contained nested highlights may have no visible remainder; those notes remain accessible in the Notes tab.

## 7. Database schema

Schema verified from `backend\data\dev.db` using `PRAGMA table_info`.

### 7.1 Core tables

| Table | Columns |
|---|---|
| `chunks` | `id VARCHAR PK`, `paper_id VARCHAR FK`, `section VARCHAR`, `page INTEGER`, `ordinal INTEGER`, `text TEXT`, `token_count INTEGER`, `vector_id VARCHAR`, `embedding_json JSON` |
| `citations` | `id VARCHAR PK`, `turn_id VARCHAR FK`, `chunk_id VARCHAR FK`, `claim_text TEXT`, `ordinal INTEGER`, `paper_id VARCHAR`, `section VARCHAR`, `page INTEGER`, `quote TEXT`, `match_score FLOAT NULL` |
| `comparison_reports` | `id VARCHAR PK`, `space_id VARCHAR FK`, `paper_ids JSON`, `matrix JSON`, `commonalities JSON`, `contradictions JSON`, `gaps JSON`, `confidence FLOAT`, `generated_at DATETIME` |
| `notes` | `id VARCHAR PK`, `space_id VARCHAR FK`, `paper_id VARCHAR FK`, `content TEXT`, `source VARCHAR`, `created_at DATETIME`, `updated_at DATETIME`, `chunk_id VARCHAR FK`, `anchor_quote TEXT`, `anchor_start INTEGER`, `anchor_end INTEGER`, `color VARCHAR` |
| `paper_profiles` | `id VARCHAR PK`, `paper_id VARCHAR FK UNIQUE`, `problem TEXT`, `method TEXT`, `dataset TEXT`, `metrics TEXT`, `results TEXT`, `limitations TEXT`, `future_work TEXT`, `generated_at DATETIME`, `verified BOOLEAN` |
| `papers` | `id VARCHAR PK`, `owner_id VARCHAR FK` (nullable until first-admin claim), `doi`, `arxiv_id`, `content_hash` (each unique per owner), remaining bibliographic and ingest fields |
| `pins` | `id VARCHAR PK`, `space_id VARCHAR FK`, `paper_id VARCHAR FK`, `pinned_at DATETIME`; unique `(space_id, paper_id)` |
| `research_spaces` | `id VARCHAR PK`, `user_id VARCHAR FK`, `name VARCHAR`, `status VARCHAR`, `created_at DATETIME`, `updated_at DATETIME` |
| `space_memory` | `space_id VARCHAR PK/FK`, `rolling_summary TEXT`, `findings JSON`, `open_questions JSON`, `updated_at DATETIME` |
| `turns` | `id VARCHAR PK`, `space_id VARCHAR FK`, `role VARCHAR`, `content TEXT`, `created_at DATETIME`, `session_id VARCHAR FK NULL` (indexed), `mentions JSON NULL` (`[{id, title}]` of @-mentioned chats on user turns) |
| `chat_sessions` | `id VARCHAR PK`, `space_id VARCHAR FK` (indexed), `title VARCHAR`, `pinned BOOLEAN`, `archived BOOLEAN`, `summary TEXT NULL`, `summary_turn_count INTEGER`, `summary_updated_at DATETIME NULL`, `created_at DATETIME`, `updated_at DATETIME` |
| `users` | `id VARCHAR PK`, `email VARCHAR UNIQUE INDEX`, `password_hash VARCHAR`, `is_admin BOOLEAN`, `created_at DATETIME` |
| `auth_sessions` | `token_hash VARCHAR PK`, `user_id VARCHAR FK`, `idle_expires_at DATETIME`, `absolute_expires_at DATETIME` |
| `linkedin_oauth_states` | Hashed state and owner/session binding with a ten-minute expiry. |
| `linkedin_connections` | Owner ID, Fernet-encrypted member token, member ID, token expiry. |
| `linkedin_post_attempts` | Unique owner/request ID, selected item ID and outcome; a retry cannot publish twice. |
| `legacy_claim_audits` | Bootstrap owner ID, exact pre-existing FK violations and missing comparison IDs, unreferenced paper IDs, audit timestamp. |
| `openalex_consents` | `user_id` owner FK/PK, `state` (`unset`, `granted`, `declined`), nullable contact email and updated timestamp. Only a granted owner record contributes a mailto to that owner's OpenAlex request. |
| `verification_iterations` | `id VARCHAR PK`, `turn_id VARCHAR FK`, `iteration INTEGER`, `draft_text TEXT`, `verdict VARCHAR`, `overall_score FLOAT`, `claim_findings JSON`, `missing_evidence_queries JSON`, `action_taken VARCHAR`, `latency_ms INTEGER`, `model_used VARCHAR`, `created_at DATETIME` |

Application connections set `PRAGMA foreign_keys=ON`, `journal_mode=WAL`, and `busy_timeout=5000`. A raw standalone SQLite connection may show `foreign_keys=0` because that pragma is connection-local.

## 8. REST API reference

Generated from live `http://localhost:8321/openapi.json`.

| Method | Path | Request | Response | Errors |
|---|---|---|---|---|
| GET | `/v1/admin/health` | None | Health summary | 200 |
| GET | `/v1/admin/models` | None | Model name map | 200 |
| GET | `/v1/search/tags` | None | List of domain tags | 200 |
| POST | `/v1/spaces` | `SpaceCreate { name }` | Space summary | 422 validation |
| GET | `/v1/spaces` | None | Space list | 200 |
| GET | `/v1/spaces/{space_id}` | Path `space_id` | Space detail with pins | 404, 422 |
| PATCH | `/v1/spaces/{space_id}` | `SpaceUpdate { name }` | Space detail | 404, 422 |
| DELETE | `/v1/spaces/{space_id}` | Path `space_id` | Delete result | 404, 422 |
| POST | `/v1/spaces/{space_id}/archive` | Path `space_id` | Space summary | 404, 422 |
| POST | `/v1/spaces/{space_id}/unarchive` | Path `space_id` | Space summary | 404, 422 |
| POST | `/v1/spaces/{space_id}/duplicate` | Optional `SpaceDuplicateRequest { copy_notes, name }` | Space summary | 404, 422 |
| GET | `/v1/spaces/{space_id}/turns` | Query `limit` default 100 | Turns with citations | 404, 422 |
| GET | `/v1/spaces/{space_id}/memory` | Path `space_id` | Space memory | 404, 422 |
| GET | `/v1/spaces/{space_id}/search-content` | Query `q` | Matching notes and turns | 404, 422 |
| POST | `/v1/spaces/{space_id}/search` | `SearchQuery` | `RankedPaperList` with results, web_results, source_health | 422 validation |
| POST | `/v1/spaces/{space_id}/papers` | `RawPaperRecord`, optional query `background=true` | `IngestJob` (`QUEUED` in background mode; poll status) | 404, 422 |
| POST | `/v1/spaces/{space_id}/papers/unpin` | `BulkUnpinRequest { paper_ids }` (1 to 200) | `{ space_id, unpinned: [ids] }` | 404, 422 |
| POST | `/v1/spaces/{space_id}/papers/upload` | Multipart `file` (PDF), optional `title` | `IngestJob` | 401, 403, 404, 413, 422 |
| DELETE | `/v1/spaces/{space_id}/papers/{paper_id}` | Path IDs | Unpin result | 422 |
| POST | `/v1/spaces/{space_id}/web-captures` | `WebCaptureRequest { url, title, content }` | `IngestJob` | 422 or capture validation errors |
| GET | `/v1/papers/{paper_id}` | Path `paper_id` | Paper DTO or detail not found object | 422 |
| GET | `/v1/papers/{paper_id}/content` | Path `paper_id`, optional `space_id`, `limit` 1 to 500 | Paper and ordered chunks | 404, 422 |
| GET | `/v1/papers/{paper_id}/file` | Path `paper_id` | Private uploaded PDF, no-store | 401, 404 |
| GET | `/v1/papers/{paper_id}/status` | Path `paper_id` | `{ paper_id, status }` | 404, 422 |
| POST | `/v1/spaces/{space_id}/chat` | `ChatRequest { question, session_id?, mentioned_session_ids? }` | `AnsweredTurn` (includes `session_id`) | 404, 409 archived session, 422, LLM degraded as low-confidence result |
| GET | `/v1/spaces/{space_id}/chat-sessions` | Query `status` (`active`, `archived`, `all`), optional `q`, `limit` 1 to 500 | Sessions, pinned first then most recent; `q` matches titles and message text | 404, 422 |
| POST | `/v1/spaces/{space_id}/chat-sessions` | Optional `ChatSessionCreate { title }` | Session | 404, 422 |
| GET | `/v1/chat-sessions/{session_id}` | Path `session_id` | Session with `turn_count`, `last_message` | 404 |
| PATCH | `/v1/chat-sessions/{session_id}` | `ChatSessionUpdate { title?, pinned?, archived? }` | Session | 404, 422 |
| DELETE | `/v1/chat-sessions/{session_id}` | Path `session_id` | `{ id, deleted }`; removes turns, citations and trails | 404 |
| GET | `/v1/chat-sessions/{session_id}/turns` | Query `limit` 1 to 1000 (default 200) | Turns oldest first with citations and mentions | 404, 422 |
| POST | `/v1/chat-sessions/{session_id}/compress` | Path `session_id` | Session with `summary`, `summary_turn_count` | 404, 409 fewer than 8 messages, 503 model unavailable |
| GET | `/v1/turns/{turn_id}/verification` | Path `turn_id` | Verification iterations | 422 |
| POST | `/v1/spaces/{space_id}/compare-jobs` | `CompareJobRequest { paper_ids, refresh, check_novelty, tier?, corpus_id }` | 202 `JobDTO` | 404, 422 |
| GET | `/v1/compare-jobs/{job_id}` | Path `job_id` | `JobDTO` (phase, progress, pending sections, warnings) | 404 |
| POST | `/v1/compare-jobs/{job_id}/cancel` | Path `job_id` | `JobDTO` | 404 |
| GET | `/v1/spaces/{space_id}/comparisons` | Path `space_id` | Grounded report summaries | 404, 422 |
| GET | `/v1/comparisons/{report_id}` | Path `report_id` | Grounded comparison report | 404, 410 retired profile-only report |
| POST | `/v1/papers/{paper_id}/evidence/rebuild` | Optional query `tier` | 202 `JobDTO` | 404 |
| GET | `/v1/papers/{paper_id}/evidence` | Path `paper_id` | Evidence ledger and audit record | 404 |
| POST | `/v1/spaces/{space_id}/notes` | `NoteCreate` | Note DTO | 404, 422 |
| GET | `/v1/spaces/{space_id}/notes` | Optional query `paper_id` | Notes | 404, 422 |
| POST | `/v1/spaces/{space_id}/papers/{paper_id}/notes/auto` | Query `refresh` | Note DTO | 404, 422 |
| GET | `/v1/spaces/{space_id}/papers/{paper_id}/annotations` | Path IDs | Anchored notes | 404, 422 |
| GET | `/v1/notes/{note_id}` | Path `note_id` | Note DTO | 404, 422 |
| PUT | `/v1/notes/{note_id}` | `NoteUpdate { content }` | Note DTO | 404, 422 |
| DELETE | `/v1/notes/{note_id}` | Path `note_id` | `{ ok: true }` | 404, 422 |

### 8.1 Request schemas from OpenAPI

| Schema | Required fields | Optional and default fields |
|---|---|---|
| `ChatRequest` | `question: string` | `session_id` (omit to continue the most recent active chat, or start one), `mentioned_session_ids` (max 5) |
| `ChatSessionCreate` | None | `title` (max 200, defaults to "New chat" and is auto-titled from the first question) |
| `ChatSessionUpdate` | None | `title`, `pinned`, `archived` |
| `CompareRequest` | `paper_ids: array` | `refresh: boolean = false` |
| `NoteCreate` | None | `paper_id`, `content = ""`, `chunk_id`, `anchor_quote`, `anchor_start`, `anchor_end`, `color` |
| `NoteUpdate` | None | `content = ""` |
| `RawPaperRecord` | `source`, `title` | `authors`, `year`, `venue`, `abstract`, `doi`, `arxiv_id`, `pmid`, `openalex_id`, `citation_count = 0`, `oa_status`, `pdf_url`, `url`, `raw_payload` |
| `SearchFilters` | None | `year_min`, `year_max`, `sources`, `open_access_only = false`, `venue`, `author`, `min_citations` |
| `SearchQuery` | `query` | `filters`, `limit = 20` range 1 to 100, `include_web = false`, `domain_tags`, `arxiv_categories`, `query_terms` |
| `SpaceCreate` | `name` | None |
| `SpaceUpdate` | `name` minimum length 1 | None |
| `SpaceDuplicateRequest` | None | `copy_notes = false`, `name` |
| `WebCaptureRequest` | `url` | `title`, `content` |

## 9. Error handling and degradation matrix

| Failure | Handling |
|---|---|
| Source timeout | `SourceRegistry` marks source DEGRADED and returns other sources. |
| Circuit open | Source marked UNAVAILABLE. |
| Missing Semantic Scholar key | Adapter raises skip error; registry reports degraded; search continues. |
| Unsafe PDF or web URL | Rejects or returns no PDF text; capture route raises validation error for explicit capture. |
| Oversized PDF or page | Rejects oversized download. |
| Non-PDF content at PDF URL | Rejected by magic byte check. |
| Robots disallow full web capture | Raises `blocked by robots.txt for this user agent`. |
| Embedding count or dimension mismatch | Raises before publishing chunks; ingest returns FAILED. |
| Pin removed during ingest | Ingest avoids publishing to runtime store and reports race-safe message. |
| Ollama unavailable during chat | Returns abstention or best-effort result with low-confidence warning. |
| Reviewer malformed JSON | Converts to REVISE verdict with feedback asking for shorter factual sentences. |
| Reviewer omits claims | `prepare_verdict` forces REVISE until every claim is covered. |
| SQLite locked | `retry_sqlite_locked` retries write operations. |
| Note anchor invalid | 422 for missing content and quote, missing chunk, chunk-paper mismatch, or `anchor_end < anchor_start`. |
| Compare with fewer than two papers | 422. |
| Compare paper not pinned | 404 with missing paper IDs. |

## 10. Testing strategy

The backend currently has 85 tests across 17 files. They cover:

- App startup smoke test.
- Domain tags, source routing, PubMed, arXiv category fragments, DuckDuckGo parsing, web provider selection, and backend avoidance of Google Scholar fetching.
- Source fan-out deadline and deduplicator correctness and performance.
- Persistence, canonical DOI/arXiv dedupe, rehydration, web capture, unsafe URL rejection, abstract-only degraded ingest, status endpoint, foreign-key configuration, citations, and verification trail persistence.
- Query rewriting regressions, including standalone pronoun rewrite and avoiding long memory blobs.
- Retrieval fusion, duplicate handling, extra query dense search, and context builder budget.
- Verification loop acceptance, revise then approve, re-retrieve, exhaustion, unsupported claim stripping, reject abstention, timeout, LLM unavailable warning, citation metadata, and evidence consistency for best draft.
- Notes, auto notes, note-context chunks, memory failure swallowing, space duplicate/delete/search, and FR-5/FR-6 routes.
- Compare profile persistence, tolerant JSON, validation, cache refresh, fixed-evidence verification, newest-report cache, and deterministic fallbacks.
- Annotation migration, content ordering, anchored note validation, and annotation ordering.

Notable regression tests:

| Test | Bug locked in |
|---|---|
| `test_rewrite_query_stays_short_and_excludes_memory_blob` | Prevents retrieval from embedding entire memory context. |
| `test_context_builder_bounds_prompt_size` | Prevents oversized prompts causing empty local drafts. |
| `test_best_draft_keeps_its_own_evidence_for_citations` | Ensures citations are validated against the evidence that produced the draft. |
| `test_embedding_count_mismatch_fails_without_partial_publish` | Prevents partial chunk publication after bad embedding responses. |
| `test_fan_out_enforces_per_source_deadline` | Ensures source latency is bounded outside httpx operation timeouts. |
| `test_deduplicator_merges_variants_and_stays_fast` | Protects identifier indexes and fuzzy-match gates. |
| `test_backend_never_fetches_google_scholar` | Keeps Scholar as a frontend deep link only. |
| `test_migrations.py` | Exercises fresh and legacy Alembic upgrades, conditional note chunk FK repair, real copied legacy data when available, unknown-schema refusal, retained backups, and orphan preservation. |

## 11. Performance optimizations

| Optimization | Before | After or result |
|---|---|---|
| Deduplicator identifier indexes and gates | O(n squared) fuzzy compare across source fan-out. | Typical batch dedupe around 2 ms. |
| Hard per-source `asyncio.timeout` | httpx per-operation timeout let slow responses exceed the intended budget. | Search completes with degraded health, about 4 to 13 seconds depending on throttling. |
| ContextBuilder 1800-word budget | Oversized prompt could produce empty drafts. | Evidence remains within local model context. |
| Ollama embedding batches of 32 | One request per chunk. | Fewer HTTP calls while preserving order. |
| Existing chunk reuse | Re-pinning could re-fetch and re-embed. | Reuses persisted chunks and vectors across spaces. |
| Query rewrite only for referential questions | Full memory/query blobs polluted retrieval. | Short standalone rewrite plus original query for fusion. |

## 12. Design vs. implementation notes

The built system is intentionally simpler than the original design docs. There is no LangGraph, Celery, Redis worker, production Postgres, GROBID parser, or required Qdrant vector database. The actual code uses FastAPI services, SQLite, pypdf, in-process ingestion, an in-memory vector store rehydrated from SQLite embeddings, and a plain async verification loop. This is the behavior documented above and verified against the source code, live OpenAPI, and `dev.db` schema.
