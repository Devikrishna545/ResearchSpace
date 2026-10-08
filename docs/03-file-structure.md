# Repository structure

R.Space is a modular FastAPI backend and an independent Next.js frontend.
Start both from the repository root with:

```powershell
python app.py
```

The launcher uses the existing backend virtual environment when available, starts
the API at `http://localhost:8321` and Next.js at `http://localhost:3000`, and stops
both process trees on Ctrl+C or a child failure. Setup and database migrations
remain explicit; see the [quickstart](../README.md#quickstart-on-windows-powershell).
Ollama must already be running. The launcher does not start Docker, install
dependencies, migrate databases, or move data.

## Entry points and routes

- [app.py](../app.py): the single local development command.
- [backend/app/main.py](../backend/app/main.py): FastAPI factory, lifespan,
  middleware, and the `/v1` mount. `app.main:app` and `app.main:create_app` remain
  supported for Uvicorn and Docker.
- [backend/app/api/v1/router.py](../backend/app/api/v1/router.py): **all backend
  route registration in one file**. Feature endpoint handlers stay with their
  modules; they are not duplicated in the launcher.
- [frontend/app](../frontend/app): Next.js route files. Routes, loading behavior,
  and UI remain unchanged.

## Backend

```text
backend/
  app/
    main.py
    api/
      router.py                    compatibility import, not another registry
      v1/
        router.py                  central route registry
        health.py
    core/                          settings, auth, ownership, logging, limits
    db/
      base.py                      declarative base and timestamps
      models.py                    explicit registration of every ORM model
      session.py                   engine, sessions, SQLite pragmas, dependencies
      retry.py                     existing SQLite-aware retry behavior
      legacy_claim_audit.py
    modules/
      auth/                        account routes and account/session ORM
      sharing/                     LinkedIn routes and connection ORM
      notes/                       api, schemas, orm, service, repository, agent
      spaces/                      api, schemas, service, space/pin/memory ORM
      papers/
        api.py
        service.py
        schemas/
        orm/
        ingestion/upload.py
      chat/
        api.py
        verification_api.py
        service.py
        sessions.py
        schemas/
        orm/
        agents/
        memory/
      discovery/
        api.py
        service.py
        schemas.py
        orm.py                     OpenAlex consent
        query_planner.py
        ranking.py
        providers/                 scholarly and web adapters
      compare/
        api.py                     saved grounded-report reads
        grounded_api.py            jobs, evidence, tiers, corpus
        service.py                 report read side
        schemas/
        orm/
        grounded/                  existing, active grounded pipeline
    platform/
      llm/                         clients, routing, JSON parsing, prompts
        prompts/templates/
      retrieval/                   retrieval, shared ingest store, vectorstore
      verification/                shared chat verification and review loop
      http/                        source client, URL checks, circuit breaker
      cache/                       existing source-result cache
      observability/               health service
    shared/                        dependency-light text, ID, timing helpers
      schemas/
  alembic/                         unchanged revisions and table definitions
  scripts/                         migration, setup-token, evaluation commands
  evaluations/                     existing evaluation inputs and reports
  tests/
    api/
      auth/
      discovery/
      papers/
    integration/database/          disposable-database migration tests
    unit/
      chat/
      compare/
      discovery/
      papers/
      platform/
      test_app_smoke.py
      test_structure_contracts.py
    test_launcher.py
  pyproject.toml
  Dockerfile
```

Small features use `schemas.py` and `orm.py`; features with multiple existing
entities use packages of the same names. This avoids merging unrelated classes
or altering SQLAlchemy mappings merely to match a diagram. Existing database
operations remain in their services; this migration does not introduce empty
repositories or rewrite persistence logic. Create a repository only when there
is actual persistence behavior to extract.

The common request dependencies are defined in `db/session.py`; the old
`core/dependencies.py` imports remain compatible and share the same engine.
Alembic and startup import `db/models.py` to register every table. No migration
revision was added.

## Grounded Compare remains active

The supplied migration proposal predates the currently implemented grounded
Compare. This reorganization **does not restore legacy profile comparison**.
The background pipeline, evidence ledger, extraction, validation, deterministic
numerics, candidate gaps, corpus checks, cache keys, model tiers, seeds, timeouts,
and report persistence are unchanged under
[modules/compare/grounded](../backend/app/modules/compare/grounded).
See the [workflow and API contracts](compare-workflow.md).

Historical profile reports remain in the database, omitted from report lists,
and return HTTP 410 when opened. The old synchronous compare endpoint stays
absent. The former `comparison_service.py` was an unused `class Service: pass`
placeholder, not a second functioning comparison implementation.

Compare jobs remain in-process asyncio tasks. There was no functioning Celery
worker to move or start, so no new worker framework or empty `platform/jobs`
package has been introduced.

## Frontend

Feature-specific components and helpers live in
[frontend/features](../frontend/features), grouped into `auth`, `chat`,
`compare`, `discovery`, `notes`, `papers`, and `spaces`. Reusable presentation
components live in [components/ui](../frontend/components/ui). The shared HTTP
client is [lib/api/client.ts](../frontend/lib/api/client.ts); shared contracts
remain in [lib/types.ts](../frontend/lib/types.ts).

Route files stay under `frontend/app`. The workspace shell owns module navigation
and a workspace header with shared context controls. Library, pinned-paper controls, and the paper reader
live in `features/papers/components`; the notes editor lives in
`features/notes/components`. Chat and Compare keep their own state and presentation
helpers. Tailwind scans the feature tree.

Visited modules stay mounted while hidden, so active requests and input state
survive module switches. `features/spaces/use-workspace-state.tsx` persists
validated view state in `sessionStorage`, scoped by authenticated user, space, and
module. It never persists credentials or browser `File` contents. Shared task
events are defined in `lib/task-events.ts`; the auth feature's notification center
stores bounded, per-user read/dismiss history in the same browser tab.

`features/spaces/components/space-context.tsx` integrates context into the workspace
header rather than a standalone card. Its expandable content displays the existing server memory
alongside recent saved notes, conversation activity, and visible comparison
findings. It refreshes after tasks and periodically while the page is visible.
This is a read-side overview, not a replacement for the backend memory or evidence
pipeline. Findings and Open questions are separate shared sections.

## Data, configuration, and review archive

- Backend `.env` and relative SQLite paths still resolve from `backend`, including
  `backend/data/dev.db`. Root `data/` remains separate and untouched.
- Local PDF uploads remain outside the repository, with the original containment
  check preserved after moving the upload module.
- `.venv`, `node_modules`, `.next`, caches, build output, and runtime data remain
  Git-ignored. They are not source modules.
- [deleted_files](../deleted_files) holds originals of moved files, unused
  placeholders, and the superseded structure document for manual review. The
  active app does not import it. The two JSON manifests record old/new paths and
  hashes; see its [review guide](../deleted_files/README.md).
- No credentials, `.env` files, databases, uploaded PDFs, or user data are copied
  into the review archive. No dependency versions or model defaults changed.

## Adding a feature

1. Add a package under `backend/app/modules/<feature>`, with its HTTP handlers,
   schemas, and service. Add ORM/repository code only if needed.
2. Register its router once in `backend/app/api/v1/router.py`, preserving the
   required authentication and ownership dependencies.
3. Register any ORM models in `backend/app/db/models.py`; create an explicit
   Alembic migration only for actual schema changes.
4. Put shared external adapters under `platform`, not a feature or `shared`.
5. Add frontend UI/helpers under `frontend/features/<feature>` and thin route
   entries under `frontend/app` when required.
6. Add tests alongside the relevant feature and API/integration tests.

## Validation

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q
cd ..\frontend
npm test
npm run lint
npm run typecheck
npm run build
```

The structure characterization tests preserve the pre-move OpenAPI contract
(59 paths), SQLite table/index/constraint definitions (26 tables), and all
30 prompt resources. Update those fingerprints only for reviewed, intentional
contract changes. Compare tests cover jobs, evidence, cache reuse, refresh,
ownership, validation, timeout recording, report persistence, and display policy.
LLM responses in these tests are deterministic fakes; passing them does not
claim a fresh live-model quality evaluation.
