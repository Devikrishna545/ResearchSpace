# R.Space

R.Space is a local-first, privacy-preserving research workspace for finding scholarly sources, pinning them into persistent research spaces, ingesting their text into local embeddings, and asking citation-verified questions against that evidence. The repository retains its existing folder and Python package names; only the product-facing name changed. The implemented application combines multi-source academic discovery, optional web capture, a paper reader with annotations, memory, comparison reports, and a hand-written peer-review verification loop that makes every grounded answer auditable.

The supplied R.Space artwork is retained in `frontend/public/brand/source.png`.
Its transparent tile crop (`tile-192.png`) serves the header and sign-in/setup
screens beside theme-aware, live `R.Space` text; `frontend/app/icon.png` is
the 64-pixel favicon. The derived full lockup (`lockup-840.png`) is retained
as a brand asset but is not rendered in the app: its dark lettering does not
contrast well on dark panels. It still says “RESEARCH ASSISTANT” and uses
navy/teal/orange rather than the app's existing indigo accent.

## Key features implemented

- Multi-source scholarly discovery through arXiv, OpenAlex, Crossref, PubMed, Semantic Scholar, and CORE adapters.
- Domain tags such as `#ml`, `#nlp`, `#medical`, and `#physics` route search toward relevant sources, arXiv categories, and query terms.
- Optional web search via DuckDuckGo Lite by default, with Brave, Tavily, and SearxNG provider hooks.
- Google Scholar deep links in the UI. The backend deliberately does not fetch Google Scholar.
- Paper pinning, PDF or abstract ingestion, page-aware chunking, local Ollama embeddings, and persistent chunk rows.
- PDF citations show a section only when a heading is actually detected in the extracted text; otherwise the section is explicitly unknown. Numbered headings work best for arXiv/CS PDFs, while other document formats have partial coverage.
- Owner-scoped local PDF uploads from the Library, with a 30 MiB limit, content-hash deduplication, authenticated original-PDF access and honest OCR-needed status for scans. Uploaded files stay outside the repository.
- Hybrid retrieval with dense vector search, sparse keyword search, RRF fusion, heuristic reranking, MMR diversification, and context budgeting.
- Phase 3 peer-review verification loop with draft generation, reviewer verdicts, policy routing, best-effort finalization, abstention, and visible verification trail.
- Compare and gap analysis over pinned papers, backed by paper profiles and the same verification loop.
- Auto notes, manual notes, anchored highlights, paper reader, and editable annotation cards.
- Persistent research spaces with archive, unarchive, duplicate, delete, turn history, memory, and content search.
- Local Argon2id email/password accounts, one-time first-admin setup, administrator provisioning/reset, revocable HttpOnly cookie sessions, CSRF/origin protection, and per-user workspace/paper ownership.
- Explicit Alembic migrations with a retained SQLite backup and fail-closed startup; individual note/finding sharing through edited copy, mailto, a locally generated PNG, and optional separately connected LinkedIn member posting.
- Account Settings in the profile-avatar menu: administrators open separate create-user and password-reset dialogs; each browser can choose Light, Dark, or System appearance. The System choice follows OS theme changes; no profile photo upload is required.

### Workspace UI and continuity

- Library, Chat, Compare, and Notes keep their context when switching modules.
  Drafts, filters, selections, and resumable request/report identifiers are saved
  per account and space in the **current browser tab** and restored after reload.
  Closing the tab ends this temporary storage; saved server data is unaffected.
- Pending chat questions remain visible while answers are generated. After a
  reload, an uncertain request is clearly labeled and can be checked against saved
  history or restored to a draft. It is never automatically resent. Browser file
  selections cannot be restored after reload; select the file again if needed.
- Library's main area shows the recent search, with author/year/source filters and
  relevance/year/author sorting. These refine fetched results without changing
  search ranking. **Clear recent search** clears that view, not pinned papers or
  server caches. Sidebar pinned papers support select-all and confirmed bulk
  removal; on mobile the pinned list can be expanded without crowding the module.
- **Space memory**, **Findings**, and **Open questions** are integrated into the
  workspace header across modules, with details expanded below its controls.
  The existing AI summary is retained; the live overview adds
  recent saved notes, conversations, and displayed findings from the latest
  comparison. Candidate gaps remain explicitly labeled as candidates.
- The notification bell reports completed or failed tasks. Read/dismissed items do
  not retain an unread badge; maintenance warnings remain reviewable without
  repeating a legacy toast on every visit. No system notification permission is
  needed. For administrators with a legacy setup audit, data-maintenance counts
  are checked against the current database, not copied from the historical setup
  snapshot. Resolved issues disappear; the original audit remains unchanged.
- The dashboard focuses on research spaces without a backend-readiness badge.
  Actual loading or connection failures still show an error and retry control.
- Compare hides the model-tier card while retaining model provenance in collapsed
  technical details. Wide matrices scroll inside the report rather than stretching
  the page; underlying models and comparison behavior are unchanged. **Previous
  reports** appears in the main column below the run controls. Saved report contents
  start hidden, including after refresh or revisiting a space; **Open** displays one
  below the list and changes to **Close** to hide it again. A new run displays its
  result in that same area unless a report was explicitly opened or closed while it
  ran. Literature corpus controls remain in the tools sidebar.
- Chat's **Export chat** downloads the selected saved conversation as Markdown or
  JSON, including original messages and citation metadata, even when the screen
  shows a compressed summary. The existing API exposes at most 1,000 turns per
  request without pagination; an incomplete export is rejected explicitly rather
  than silently truncated.
- Chat answers are generated as up to five structured claims with exact retrieved
  chunk IDs. The reviewer receives those same claim IDs and source titles;
  bibliography numbers or partial IDs are never guessed into valid citations.
  Partial or unreviewed claims cannot receive a verified badge. Valid reviewed
  claims may still be returned as explicitly unverified best effort.
- A direct definition or summary matching a full pinned paper title uses that
  paper's passages; broader and comparative questions retain multi-paper retrieval.
  Follow-up questions use their standalone rewrite for both retrieval and review,
  without treating conversation history as evidence.
- **Peer review & evidence** on each saved answer shows claim findings, reviewer
  feedback and the reviewed drafts. Evidence buttons also expose citations when
  older answers have no usable inline markers. For new answers, verification
  status, warnings, complete reviewer feedback and citation snapshots survive
  reloads (including note citations). Migration `0009_chat_verification_metadata`
  adds this storage; it does not recreate metadata missing from historical turns.
  An abstract-only paper still supplies only abstract evidence, not full-text or
  page-level support. Missing review records are shown explicitly.

Crossref titles and JATS abstracts are converted to readable text before search
and ingestion. Its publisher-provided PDF links are only **candidates**, not proof of
open access: publisher login pages, restricted responses and non-PDF content
are rejected. An available abstract can still be read as a `DEGRADED`
abstract-only paper; a record with neither accessible PDF nor abstract remains
`DEGRADED` without chunks. Re-pinning an existing record can enrich its
missing metadata; there is no automatic rewrite of saved papers. Unpaywall
lookups are not enabled: they would require a separately authorized real
contact email, not an OpenAlex-only consent address.

## Screenshots

| Area | Placeholder | Caption |
|---|---|---|
| Dashboard | `![Dashboard screenshot](docs/images/dashboard-placeholder.png)` | Research spaces and backend health. |
| Discovery | `![Discovery screenshot](docs/images/discovery-placeholder.png)` | Domain-tag search, source health, web results, and pinning. |
| Chat | `![Chat screenshot](docs/images/chat-placeholder.png)` | Verified local answers with citation popovers and trail disclosure. |
| Paper reader | `![Reader screenshot](docs/images/reader-placeholder.png)` | Page-aware chunks, highlights, and anchored notes. |
| Compare | `![Compare screenshot](docs/images/compare-placeholder.png)` | Background grounded comparison: evidence ledger, page-linked findings with evidence statuses, code-computed numerics, candidate gaps. |

The image paths are placeholders only. No screenshot files are included.

To add a paper unavailable through public source links, use **Library → Upload
your PDF** for a copy you already have. The app does not fetch from Google
Scholar or bypass publisher access controls; the existing Google Scholar link
only opens its website. Select or drop a PDF (up to 30 MiB) and optionally
override its title. Text PDFs are indexed page by page for the reader and
citations. Scanned/image-only PDFs are saved but show `DEGRADED` until OCR is
performed elsewhere and a readable file is uploaded.

## Quickstart on Windows PowerShell

### Prerequisites

- Python 3.13 or newer.
- Node.js 22.
- Ollama running locally on `http://localhost:11434`.
- Ollama models pulled locally:

```powershell
ollama pull llama3.2:3b
ollama pull gemma3
ollama pull nomic-embed-text
# Grounded Compare (student-laptop tier)
ollama pull qwen3:8b
ollama pull qwen3-vl:8b-instruct
ollama pull embeddinggemma:300m-qat-q4_0
```

The checked-in backend defaults still name older `llama3.1:8b` values in `backend\.env.example`, but the delivered local configuration uses `llama3.2:3b`, `gemma3:latest`, and `nomic-embed-text`. Compare uses its own pinned models; see [docs/compare-workflow.md](docs/compare-workflow.md) for the weak-laptop (`qwen3:4b`, `qwen3-vl:4b-instruct`) and university deep-review tiers.

### One-time setup

Install dependencies and explicitly migrate the database before launching. Start
from the repository root; the migration retains a backup of an existing SQLite
database (see the migration section below).

```powershell
cd backend
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
.\.venv\Scripts\python.exe -m scripts.migrate
cd ..\frontend
npm install
cd ..
```

### Start both servers with one command

From the repository root:

```powershell
python app.py
```

Open `http://localhost:3000`. The API is `http://localhost:8321`, with live OpenAPI
at `http://localhost:8321/openapi.json`. `make run` and `.\make.ps1 run` invoke
the same launcher.

The launcher prefers `backend\.venv\Scripts\python.exe` on Windows or
`backend/.venv/bin/python` on macOS/Linux; otherwise it uses the Python interpreter
running `app.py` and checks that it is 3.13+. It runs Uvicorn from
`backend` and the installed Next.js development CLI through Node from `frontend`
(equivalent to the current `npm run dev` script, without an npm shell).
Backend `.env`, frontend environment files, relative database paths, uploads,
and existing user data retain their current locations. The root `app.py` is
only a supervisor; backend `app.main:app` is imported in a separate backend
process, not from the root module. The combined launcher does not enable API
reload, so backend startup failures terminate supervision rather than leaving a
reloader alive with no working API. The standalone backend command below retains
the optional reload workflow.

Both servers bind to loopback only. Ports 8321 and 3000 must be free; existing
servers are never reused or stopped, and an explicit Next.js port prevents
automatic fallback to another port. Ctrl+C stops both owned process trees;
either server exiting also stops the other and returns a failure status.
Windows uses an owned Job Object (including Node/worker descendants), with
a gated base-Python child so no server starts before ownership is established;
macOS/Linux use separate process groups. Startup and cleanup errors remain
visible in the terminal. A restrictive Windows host that rejects Job Object
assignment fails explicitly instead of starting an unsupervised server.

This command does **not** install dependencies, run schema migrations, reset
accounts, or start/stop Ollama. Keep your existing Ollama service running and
pull the required models separately. Normal backend startup still performs its
existing schema checks and account-setup behavior.

### Standalone backend (optional)

To run only the API, from the repository root:

```powershell
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8321 --reload
```

### SQLite schema migrations (backend)

Run Alembic **before** starting the backend on a new database or upgrading an existing
one. It is an explicit command, not a startup hook. Run these commands from `backend`
with the server stopped; `DATABASE_URL` defaults to `sqlite+aiosqlite:///./data/dev.db`
and can be overridden for a different SQLite file. Never run the migration against
the only copy of valuable data.

From `backend`, run `.\.venv\Scripts\python.exe -m scripts.migrate`. It takes a
consistent SQLite API backup (including committed WAL data), retains it beside the
database with a timestamped `pre-alembic` name, upgrades to head, and verifies
existing table row counts. Keep an additional off-host backup for valuable data.
Do not invoke raw `alembic stamp` on an unverified database.

For a different database,
set `$env:DATABASE_URL = 'sqlite+aiosqlite:///./data/other.db'` before the commands
and the runner chooses the matching backup path. For recovery, stop the server and all DB
connections, copy the verified backup over `data\dev.db`, and remove any stale
`data\dev.db-wal` and `data\dev.db-shm` files **only after all connections have
closed**. Check `PRAGMA integrity_check` on the restored file before restarting.
Downgrades are intentionally unsupported; restore the backup instead.

The first revision creates the historical schema on an empty SQLite database. On
an existing `create_all`-managed database it validates the complete expected table,
column, foreign-key, unique-constraint and primary-key layout plus integrity before
adopting it; it supports the older optional note-anchor/citation columns and adds
any that are missing. An unknown or partially initialized schema fails rather than
being blindly stamped. Pre-existing orphaned foreign-key references are reported
and preserved rather than silently deleted; the migration rejects new broken
references, while recognizing orphaned `notes.chunk_id` values that were
already present but previously lacked an enforced FK.
Investigate existing orphans separately before relying on affected evidence.
The second revision retains existing rows and adds
`users.is_admin` (default false), an `auth_sessions` table (hashed token,
user, idle and absolute expiries), and nullable
`papers.owner_id`; DOI, arXiv ID and content hash become unique *per owner*.
Existing `users.password_hash` stays nullable. Existing spaces remain unclaimed
(`research_spaces.user_id IS NULL`) and existing papers remain unowned
(`papers.owner_id IS NULL`) until a separate explicit bootstrap/claim operation;
migrations do not assign ownership or create accounts. Startup rejects a missing
or outdated Alembic revision; it does not modify schema. On first start with no
users, the host startup output displays a one-time setup token. If that output
was lost before setup, stop the server and run
`.\.venv\Scripts\python.exe -m scripts.reset_setup_token` locally from
`backend`; it atomically replaces the stored token hash only while no accounts
exist, records a non-secret audit line, and prints the new token once. There
is no token-recovery HTTP endpoint. Enter the current token in the
setup form with an admin email and a password of at least 12 characters. The
bootstrap transaction claims existing unowned spaces and papers (including
unreferenced paper rows; the response reports their count) without changing IDs.
Ambiguous existing owners or changed/new foreign-key violations abort the
transaction. Pre-existing broken references and missing comparison papers are
recorded exactly in `legacy_claim_audits`, preserved without fabricated rows,
and shown to the administrator as a dismissible alert and a persistent notification
in the header (not a banner on each page). Missing records
remain unavailable to the reader and cannot be published to LinkedIn. The
local backup of the existing dev database has **16 originally enforced
foreign-key violations plus one previously unenforced broken note-to-chunk
reference**. After upgrading, `PRAGMA foreign_key_check` reports **17**;
the fourth revision restores that FK with a conditional SQLite table rebuild
without removing or changing notes. Three comparisons also reference absent
papers. Intact spaces and papers can still be claimed while those affected
references require manual review.
Never silently drop orphaned rows.

Run `.\.venv\Scripts\python.exe -m scripts.audit_legacy` against the database or
its backup to see the affected row IDs, missing targets, comparison references
and unpinned papers. This reads only; the report contains local IDs and should
not be published. First restore authentic missing paper/chunk rows from another
backup or original source, preserving their original IDs. If no authentic
evidence exists, a human must explicitly decide how to quarantine each
unresolved dependent pin/note/citation/comparison in a separate retained
archive and repair its live references; keep the original IDs, quotes and
findings in the archive, and never substitute invented chunks or represent
an unsupported citation as verified. Take another full SQLite backup before
manual SQL changes. Repeat `PRAGMA integrity_check`,
`PRAGMA foreign_key_check` and the audit after repairs. The application does
not delete, fake or auto-repair evidence. The third revision adds optional
LinkedIn connection, OAuth state, one-shot posting attempt and legacy claim
audit tables; it does not enable publishing by itself. The fourth revision
adds the missing note-to-chunk FK only where legacy startup DDL omitted it;
fresh schemas already have it and need no rebuild.

### Optional LinkedIn member publishing

Direct posting is disabled until a separately registered LinkedIn developer
app has the Share on LinkedIn (`w_member_social`) and OpenID profile permissions,
and the backend has all of `LINKEDIN_CLIENT_ID`, `LINKEDIN_CLIENT_SECRET`,
`LINKEDIN_TOKEN_KEY` (an externally stored Fernet key),
`LINKEDIN_MEMBER_SOCIAL_ENABLED=true`, and `LINKEDIN_REDIRECT_URI` (an
absolute, registered HTTPS URL ending at `/v1/linkedin/callback`).
Set `COOKIE_SECURE=true` behind HTTPS and use the exact frontend origin in
`CORS_ALLOW_ORIGINS`. HTTP localhost is **not** a supported LinkedIn redirect
workaround. Do not commit or log developer credentials or encryption keys.
`LINKEDIN_API_VERSION` defaults to `202609`; review currently supported API
versions before enabling. The connected member authorizes `openid profile
w_member_social`, the app encrypts the token at rest, and the preview requires
edited text, an explicit Public/Connections choice and a separate confirmation.
One-use request IDs prevent automatic duplicate publication after uncertain
network outcomes. Disconnect deletes the local token; to revoke LinkedIn's
grant as well, the member must remove the app in LinkedIn Permitted Services.
The optional integration has mock coverage; live authorization/posting cannot
be verified without an approved app, HTTPS callback, and real member consent.

### Standalone frontend (optional)

```powershell
cd frontend
npm run dev -- --hostname 127.0.0.1 --port 3000
```

Frontend URL: `http://localhost:3000`.
Open **Settings** beside Log out to view your profile, choose Light/Dark/System,
or log out everywhere. Administrators can launch separate create-account and
password-reset forms from Settings. Legacy data warnings appear once as a
dismissible alert per browser session; the bell keeps them available afterward.
Appearance is stored only in that browser; the default follows the OS.
Use the same hostname (`localhost` or `127.0.0.1`) for the frontend and API
to keep cookie-based sessions working in local development.

### Environment variables that matter

Place backend values in `backend\.env`.

| Variable | Purpose | Delivered local value or default |
|---|---|---|
| `DATABASE_URL` | SQLAlchemy database URL. | `sqlite+aiosqlite:///./data/dev.db` |
| `OLLAMA_BASE_URL` | Local Ollama host. | `http://localhost:11434` |
| `OLLAMA_MODEL_SMALL` | Query rewriting and light work. | `llama3.2:3b` |
| `OLLAMA_MODEL_MEDIUM` | Answer generation. | `llama3.2:3b` |
| `OLLAMA_MODEL_LARGE` | Late reviewer and heavier synthesis. | `gemma3:latest` |
| `OLLAMA_MODEL_VERIFY` | Peer reviewer. | `gemma3:latest` |
| `OLLAMA_MODEL_EMBED` | Embeddings for chat and search. | `nomic-embed-text` |
| `GROUNDED_TIER` | Compare model tier: `weak`, `student` or `deep`. | `student` |
| `GROUNDED_TEXT_MODEL` / `GROUNDED_VISION_MODEL` / `GROUNDED_EMBED_MODEL` | Pinned Compare models (student tier). | `qwen3:8b` / `qwen3-vl:8b-instruct` / `embeddinggemma:300m-qat-q4_0` |
| `GROUNDED_SEED` | Fixed seed for every Compare model call. | `42` |
| `GROUNDED_LLM_TIMEOUT_S` | Per-call timeout for Compare model calls. | `300` |
| `GROUNDED_MAX_VLM_PAGES` | Maximum rendered pages sent to the vision model per paper. | `12` |
| `GROUNDED_NOVELTY_MIN_CORPUS` | Minimum searchable corpus items before novelty is assessed. | `20` |
| `OLLAMA_TIMEOUT_S` | Ollama HTTP timeout. | `120` in local `.env`; config default is `15`. |
| `SOURCE_USER_AGENT` | Base User-Agent sent to public scholarly APIs. | `research-assistant/0.1`; do not add a made-up mailto address. |
| `SOURCE_CONTACT_EMAIL` | Optional generic contact in User-Agent headers for other public sources; it is **not** used to identify signed-in members to OpenAlex. | Unset by default. |
| `SEMANTIC_SCHOLAR_API_KEY` | Required before the Semantic Scholar adapter is used. | Optional but recommended. |
| `CORE_API_KEY` | Enables CORE results. | Optional. |
| `PUBMED_API_KEY` | Raises PubMed E-utilities limits. | Optional. |
| `WEB_SEARCH_PROVIDER` | Web provider. | `duckduckgo`; alternatives: `brave`, `tavily`, `searxng`. |
| `BRAVE_API_KEY`, `TAVILY_API_KEY`, `SEARXNG_URL` | Provider-specific web search settings. | Optional. |
| `SOURCE_TIMEOUT_S` | Hard per-source discovery deadline; network read timeout is shorter. | `12.0`. |
| `UPLOAD_DIR` | Private per-owner PDF storage outside the repository; reject paths inside the source tree. | `%LOCALAPPDATA%\R.Space\uploads` on Windows. |
| `SOURCE_CACHE_TTL_S` | In-process lifetime for successful scholarly/web source results. | `900` (15 minutes). |
| `SOURCE_CACHE_MAX_ENTRIES`, `SOURCE_CACHE_MAX_BYTES` | Maximum entries and bytes retained in the process; oversized responses bypass the cache. | `256` and `33554432` (32 MiB). |
| `RANKING_RECENCY_WEIGHT` | Optional capped recency tie signal, audited on landmark queries; requires a separate recent-intent evaluation before enabling. | `0.0` (off). |
| `RANKING_REMOVE_STOPWORDS` | Optional grammatical query-term filtering, audited on the frozen ranking set. | `false` (off). |
| `LOOP_MAX_ITERATIONS` | Verification loop iteration cap. | `3`. |
| `LOOP_WALL_CLOCK_CAP_MS` | Verification wall-clock cap. | `120000` in local `.env`; config default is `20000`. |
| `LOOP_ACCEPTANCE_THRESHOLD` | Reviewer score needed for approval. | `0.90`. |

Scholarly and web sources share one pooled HTTP client across searches instead
of building a TLS client per adapter. Provider API keys are attached only to
their own requests, never to the shared client's default headers. On a new
member's first sign-in, an optional OpenAlex prompt explains that an address
they choose is sent with **each** scholarly search so OpenAlex can contact
them about API usage; consenting enables its polite pool and separate credit
allocation. Choices are account email, a different address they control, or
decline. A skipped or declined choice still permits searching under the lower
shared rate limits. Each member can change or withdraw consent in Settings;
the address is sent in OpenAlex's `mailto` query parameter and User-Agent
**only while that member's consent is granted**. One member's address is
never reused for another. No app-wide OpenAlex address is configured.
The old `local@example.invalid` is reserved and non-deliverable, not a real
contact. HTTP 429 is reported as `rate_limited` with upstream `Retry-After`
when available, without an automatic deadline-consuming retry. Semantic
Scholar still requires its own API key.

Repeated searches in one API process can reuse **successful raw per-source
candidate responses** for 15 minutes, up to 256 entries/32 MiB. Cache keys
include the authenticated owner, source/provider and exact search parameters.
OpenAlex's `mailto` does not change its public result set and is not copied
into cache keys, but the owner remains part of every key: one member cannot
receive another member's cached response. Hits still go through the current
normalizer, deduplicator and ranker. Errors, 429s, timeouts and interrupted
source calls are never cached, so a failed source is retried. This cache is
in-process only and cleared at shutdown; it is not shared across workers.

## How it works

A user asks a question inside a research space. The backend rewrites referential follow-ups into a short standalone retrieval query, retrieves pinned paper chunks with dense and sparse search, packs a bounded evidence set, drafts an answer with citations, and sends the draft to a separate peer reviewer. Loop policies validate claim coverage and citation IDs, route to regenerate or re-retrieve when needed, and either accept, return a best-effort answer with low-confidence warning, or abstain. Citations and every verification iteration are persisted and displayed in the UI.

## Tech stack

| Layer | Implemented technology |
|---|---|
| Frontend | Next.js, React, TypeScript, Tailwind CSS, lucide-react, react-markdown |
| Backend API | FastAPI, Pydantic, SQLAlchemy asyncio, aiosqlite |
| Local inference | Ollama chat and embedding APIs |
| Discovery | httpx source adapters for arXiv, OpenAlex, Crossref, PubMed, Semantic Scholar, CORE, and web search providers |
| Retrieval | In-process vector store plus SQLite-persisted embeddings, TF-IDF-like sparse search, RRF, rerank, MMR |
| Persistence | SQLite development database at `backend\data\dev.db` |
| Tests | pytest and pytest-asyncio for backend; native Node UI-state tests, TypeScript, ESLint, and Next build for frontend |

## Project layout

See [File structure](docs/03-file-structure.md) for the complete current layout,
feature boundaries, and retained compatibility paths. Key entry points:

```text
research-assistant\
  app.py                   single-command FastAPI + Next.js launcher
  backend\
    app\
      main.py              FastAPI application (app.main:app)
      api\v1\router.py     central API router
      api\router.py        retained compatibility shim
      modules\compare\
        grounded\          active grounded comparison implementation
    data\dev.db            SQLite development database
    tests\
      unit\compare\        comparison unit tests
      test_launcher.py     isolated launcher tests
  frontend\
    app\                   Next.js app routes
  docs\03-file-structure.md complete current project structure
```

## Testing and validation commands

The backend suite contains migration, authorization and research-service tests.
The frontend has native Node regression tests for dashboard request ordering,
pre-paint theme initialization, OS preference changes and avatar initials. Run each block
from the extracted project root in a separate shell.

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q
```

Comparison unit tests are in
[`backend/tests/unit/compare`](backend/tests/unit/compare). Run only those tests
from the repository root:

```powershell
.\backend\.venv\Scripts\python.exe -m pytest backend\tests\unit\compare -q
```

Launcher-only checks (from the repository root) do not import the backend or
touch a database:

```powershell
.\backend\.venv\Scripts\python.exe -m pytest backend\tests\test_launcher.py -q
# Optional real-process smoke tests: ephemeral ports and dummy Python/Node trees only.
$env:RSPACE_LAUNCHER_RUNTIME_TEST = '1'
.\backend\.venv\Scripts\python.exe -m pytest backend\tests\test_launcher.py -q
Remove-Item Env:RSPACE_LAUNCHER_RUNTIME_TEST
```

The opt-in tests verify cleanup after both a child exit and an interrupt, without
launching FastAPI, Next.js, or Ollama. On macOS/Linux, set
`RSPACE_LAUNCHER_RUNTIME_TEST=1` for the equivalent pytest command.

Frontend validation commands:

```powershell
cd frontend
npm test
npm run typecheck
npm run lint
npm run build
```

## Known limitations and caveats

- Small local models can be slow or conservative, and may abstain when evidence is thin.
- Public scholarly APIs have rate limits. Semantic Scholar is intentionally skipped unless `SEMANTIC_SCHOLAR_API_KEY` is set.
- SQLite is the default development database. There is no production Postgres migration path wired yet.
- LinkedIn direct posting is configuration-gated and unverified against live developer credentials; it reports unavailable until configured. Other sharing targets remain local/manual.
- Authentication and SQLite/single-process rate limits do not make a public deployment safe: require HTTPS, secure cookies (`COOKIE_SECURE=true`), durable backups, shared multi-instance rate limiting, logging/monitoring, quotas, and dependency/vulnerability checks before internet exposure.
- The local legacy database has 17 broken references after enforcing the missing note FK and three comparisons with absent papers; claiming intact data is possible, but affected evidence requires manual reconciliation before it can be used or published.
- Celery and LangGraph were not adopted. The verification loop is a plain async Python driver.
- Qdrant and GROBID are configured or stubbed but not required. The delivered path stores embeddings in SQLite JSON and an in-memory vector store, and parses PDFs with `pypdf`.
- Highlight rendering clips overlapping ranges. Fully nested highlights can be hidden in the reader, though notes remain accessible from the Notes tab.
- Exact-paper lookup methods exist on the adapter interface but are not implemented as live routes.

## Roadmap

1. Reconcile existing SQLite orphan references and review the degraded legacy corpus before relying on it.
2. Validate optional LinkedIn publishing with an approved app and registered HTTPS callback before relying on it.
3. Move embeddings to a real Qdrant collection or another durable vector index.
4. Add a production database profile, likely Postgres.
5. Add a worker queue for long ingestion and comparison jobs if concurrent use grows.
6. Improve PDF structure extraction, potentially with GROBID, while preserving the current SSRF and size guards.
7. Add screenshot assets and user-facing docs once UI screenshots are captured.
8. Add evaluation datasets for verification accuracy, latency, and abstention behavior.
