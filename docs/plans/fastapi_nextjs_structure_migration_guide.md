# FastAPI and Next.js Structure Migration Guide

## Purpose

Reorganize the Research Assistant repository into feature-oriented FastAPI modules and Next.js frontend features. The goal is clearer ownership, simpler maintenance, and safer extension of Papers, Compare, Chat, Discovery, Notes, and Spaces.

## Non-negotiable migration rule

> **This restructuring must not change application functionality or behavior.**

This is a code-organization refactor only. It must not change API contracts, database behavior, model selection, prompts, output formats, authorization, caching, timeouts, worker semantics, or user-visible experience.

Do not combine this work with the grounded Compare rebuild, model replacement, prompt edits, schema changes, dependency upgrades, endpoint redesign, or UI redesign. Deliver functional changes later, in separate tested changes.

## Current-state assessment

The backend is already FastAPI-based, but it is grouped mainly by technical layer:

~~~
models/
schemas/
services/
repositories/
agents/
grounded/
verification/
~~~

That splits a single feature across many folders. Compare is the clearest example: its code sits across API routes, services, models, schemas, agents, grounded code, and verification. It also has both \`compare_service.py\` and \`comparison_service.py\`, so its boundary should be made explicit.

The recommended target is a **modular monolith**: organize product behavior by feature and put common external adapters in explicit platform packages.

## Target repository layout

~~~
research-assistant/
├─ backend/
│  ├─ app/
│  │  ├─ main.py
│  │  ├─ api/
│  │  │  ├─ v1/
│  │  │  │  ├─ router.py
│  │  │  │  └─ health.py
│  │  │  └─ dependencies.py
│  │  ├─ core/
│  │  │  ├─ config.py
│  │  │  ├─ auth.py
│  │  │  ├─ logging.py
│  │  │  ├─ exceptions.py
│  │  │  ├─ ownership.py
│  │  │  └─ upload_limit.py
│  │  ├─ db/
│  │  │  ├─ session.py
│  │  │  ├─ base.py
│  │  │  └─ migrations_helpers.py
│  │  ├─ modules/
│  │  │  ├─ auth/
│  │  │  ├─ papers/
│  │  │  ├─ compare/
│  │  │  ├─ chat/
│  │  │  ├─ spaces/
│  │  │  ├─ notes/
│  │  │  └─ discovery/
│  │  ├─ platform/
│  │  │  ├─ llm/
│  │  │  ├─ retrieval/
│  │  │  ├─ storage/
│  │  │  ├─ jobs/
│  │  │  ├─ cache/
│  │  │  └─ observability/
│  │  └─ shared/
│  │     ├─ schemas/
│  │     ├─ text/
│  │     ├─ identifiers.py
│  │     ├─ pagination.py
│  │     ├─ retry.py
│  │     └─ timing.py
│  ├─ alembic/
│  ├─ evaluations/
│  ├─ scripts/
│  ├─ tests/
│  │  ├─ unit/
│  │  ├─ integration/
│  │  ├─ api/
│  │  └─ fixtures/
│  ├─ pyproject.toml
│  └─ Dockerfile
├─ frontend/
│  ├─ app/
│  ├─ features/
│  │  ├─ compare/
│  │  ├─ papers/
│  │  ├─ chat/
│  │  ├─ spaces/
│  │  ├─ notes/
│  │  └─ discovery/
│  ├─ components/
│  │  └─ ui/
│  ├─ lib/
│  │  ├─ api/
│  │  └─ utils/
│  ├─ public/
│  └─ tests/
├─ docs/
├─ infra/
│  ├─ docker/
│  └─ compose/
├─ scripts/
├─ data/                 # local runtime data only; ignored by Git
├─ docker-compose.yml
├─ Makefile
└─ README.md
~~~

## Backend module convention

Each product module uses the same small structure:

~~~
modules/<feature>/
├─ __init__.py
├─ api.py              # FastAPI router; HTTP concerns only
├─ schemas.py          # Pydantic request, response, and internal DTOs
├─ orm.py              # SQLAlchemy entities for this feature
├─ repository.py       # Persistence operations only
├─ service.py          # Use-case orchestration
└─ feature-specific packages and helpers
~~~

| Layer | Responsibility | Must not contain |
|---|---|---|
| \`api.py\` | Request parsing, dependencies, response conversion, HTTP status codes | SQL queries, prompts, LLM calls, feature logic |
| \`schemas.py\` | Pydantic DTOs and boundary validation | SQLAlchemy mappings or orchestration |
| \`orm.py\` | SQLAlchemy entities | API response handling |
| \`repository.py\` | Database reads/writes | Prompt construction or HTTP logic |
| \`service.py\` | Use-case orchestration | Route decorators and scattered raw SQL |
| \`platform/\` | Shared technical adapters | Feature-specific policy |

## Feature structure and exact moves

### Papers

~~~
modules/papers/
├─ api.py
├─ schemas.py
├─ orm.py
├─ repository.py
├─ service.py
├─ ingestion/
│  ├─ pdf_parser.py
│  ├─ chunking.py
│  ├─ document_structure.py
│  └─ upload.py
└─ extraction/
   ├─ tables.py
   ├─ figures.py
   └─ metadata.py
~~~

| Current location | Target |
|---|---|
| \`app/api/v1/papers.py\` | \`app/modules/papers/api.py\` |
| \`app/services/paper_service.py\` | \`app/modules/papers/service.py\` |
| \`app/services/pdf_upload.py\` and \`app/ingestion/*\` | \`app/modules/papers/ingestion/\` |
| paper/chunk/profile ORM models | \`app/modules/papers/orm.py\` |
| paper schemas | \`app/modules/papers/schemas.py\` |
| paper/chunk repositories | \`app/modules/papers/repository.py\` |

### Compare

Compare needs one clear home:

~~~
modules/compare/
├─ api.py
├─ schemas.py
├─ orm.py
├─ repository.py
├─ service.py
├─ jobs.py
├─ legacy/
│  └─ profile_compare.py
├─ evidence/
├─ extraction/
├─ validation/
├─ comparison/
├─ numerics/
├─ gaps/
└─ novelty/
~~~

For this structural move, keep the current profile-based comparison under \`legacy/\` or equivalent compatibility locations. Do **not** activate the future grounded workflow in this refactor.

| Current location | Target |
|---|---|
| \`app/api/v1/compare.py\` | \`app/modules/compare/api.py\` |
| \`app/services/compare_service.py\` | \`app/modules/compare/legacy/profile_compare.py\` initially |
| \`app/services/comparison_service.py\` | Keep separate at first; merge only after characterization tests pass |
| Compare-specific agents | \`app/modules/compare/legacy/\` initially |
| comparison/verification ORM models | \`app/modules/compare/orm.py\` |
| comparison/verification schemas | \`app/modules/compare/schemas.py\` |
| comparison/verification repositories | \`app/modules/compare/repository.py\` |
| \`app/grounded/*\` | \`app/modules/compare/\` subpackages, retaining compatibility imports |
| Compare-only verification code | \`app/modules/compare/validation/\` after a usage audit |

Before moving \`verification/\`, search all usages. If it is used by Chat or other features, put it under \`platform/verification/\` rather than Compare.

### Chat, Spaces, Notes, and Discovery

~~~
modules/chat/
├─ api.py
├─ schemas.py
├─ orm.py
├─ repository.py
├─ service.py
└─ memory/

modules/spaces/
├─ api.py
├─ schemas.py
├─ orm.py
├─ repository.py
└─ service.py

modules/notes/
├─ api.py
├─ schemas.py
├─ orm.py
├─ repository.py
└─ service.py

modules/discovery/
├─ api.py
├─ schemas.py
├─ service.py
├─ ranking.py
└─ providers/
   ├─ base.py
   ├─ crossref.py
   ├─ semantic_scholar.py
   ├─ openalex.py
   ├─ pubmed.py
   ├─ arxiv.py
   ├─ unpaywall.py
   └─ web_search.py
~~~

Move external source adapters from \`app/sources/\` into \`modules/discovery/providers/\`. Keep generic HTTP, retry, and cache mechanics in \`platform/\` or \`shared/\`.

## Platform packages

### LLM

~~~
platform/llm/
├─ ollama_client.py
├─ model_router.py
├─ provider.py
├─ streaming.py
├─ token_counter.py
├─ structured_output.py
├─ guardrails.py
└─ prompts.py
~~~

Move current \`app/llm/*\` here. Preserve environment names, model routing, model fallback order, timeouts, temperatures, seeds, prompts, and parsing behavior exactly.

### Retrieval

~~~
platform/retrieval/
├─ embeddings.py
├─ vector_store.py
├─ hybrid_retriever.py
├─ dense_search.py
├─ sparse_search.py
├─ fusion.py
├─ mmr.py
├─ reranker.py
├─ context_builder.py
└─ query_rewriter.py
~~~

Consolidate the technical pieces currently split across \`app/retrieval/\` and \`app/vectorstore/\`. These are shared adapters used by features, not a product feature themselves.

### Jobs and runtime services

Use:

~~~
platform/jobs/
platform/storage/
platform/cache/
platform/observability/
~~~

Preserve worker task paths, queue names, task payloads, environment variables, and execution semantics during this move.

## Core and shared packages

Use \`core/\` only for app-wide runtime matters:

~~~
config.py
auth.py
dependencies.py
exceptions.py
logging.py
ownership.py
upload_limit.py
~~~

Use \`shared/\` only for small dependency-light utilities. Do not put feature policies, SQLAlchemy code, Ollama code, or vector-store code into \`shared/\`.

## API router rules

Keep public endpoint paths and response contracts unchanged. The central router should register module routers:

~~~python
from app.modules.compare.api import router as compare_router
from app.modules.papers.api import router as papers_router
from app.modules.chat.api import router as chat_router
from app.modules.spaces.api import router as spaces_router

api_router.include_router(compare_router)
api_router.include_router(papers_router)
api_router.include_router(chat_router)
api_router.include_router(spaces_router)
~~~

For every endpoint, preserve:

- route prefix and path;
- request and response bodies;
- error payloads and status codes;
- auth/ownership dependencies;
- OpenAPI behavior;
- cache behavior;
- timeout behavior.

## Database and Alembic rules

1. Keep \`alembic/\` at \`backend/alembic/\`.
2. Do not change tables or create migrations merely because ORM files move.
3. Preserve table names, foreign keys, indexes, constraints, and metadata registration.
4. Ensure Alembic imports the new ORM locations before migration operations.
5. Run migration tests against a disposable database after every feature move.
6. Do not rename a Python ORM class and database table in the same change unless compatibility is demonstrated.

## Frontend structure

Keep Next.js independent from FastAPI:

~~~
frontend/
├─ app/
│  ├─ layout.tsx
│  ├─ page.tsx
│  └─ spaces/[id]/page.tsx
├─ features/
│  ├─ compare/
│  │  ├─ components/
│  │  ├─ hooks/
│  │  ├─ api.ts
│  │  └─ types.ts
│  ├─ papers/
│  ├─ chat/
│  ├─ spaces/
│  ├─ notes/
│  └─ discovery/
├─ components/
│  └─ ui/
├─ lib/
│  ├─ api/
│  │  ├─ client.ts
│  │  └─ errors.ts
│  └─ utils/
├─ public/
└─ tests/
~~~

Rules:

- keep route files in \`frontend/app/\`;
- move feature-specific components into \`frontend/features/<feature>/components/\`;
- keep only reusable presentation primitives in \`frontend/components/ui/\`;
- preserve API calls, serialization, loading states, errors, routing, and UI behavior;
- do not redesign ComparePanel, ComparisonView, or workspace screens in this migration.

## Runtime and generated directories

These are not source architecture and must remain Git-ignored:

~~~
backend/.venv/
backend/.pytest_cache/
backend/research_assistant_backend.egg-info/
frontend/.next/
frontend/node_modules/
~~~

There are root-level and backend-level data directories. Do not silently move runtime data in this refactor. Adopt this target only after behavior preservation is proven:

~~~
data/                    local runtime data, Git-ignored
backend/tests/fixtures/  committed test fixtures only
~~~

Do not relocate databases, uploaded PDFs, vector indexes, caches, or user files without an explicit data migration, backup, and rollback plan.

## Imports and compatibility shims

Use absolute imports:

~~~python
from app.modules.compare.service import CompareService
from app.platform.llm.ollama_client import OllamaClient
from app.core.config import settings
~~~

Avoid deep relative imports. Use temporary compatibility re-exports while dependencies move:

~~~python
# Temporary compatibility shim: app/services/compare_service.py
from app.modules.compare.legacy.profile_compare import CompareService

__all__ = ["CompareService"]
~~~

Remove a shim only after all imports, tests, scripts, workers, and container entry points have moved successfully.

## Migration process

### Phase 0 — behavioral baseline

Before moving files:

1. Run backend unit, integration, API, and migration tests.
2. Run frontend lint, typecheck, build, and tests.
3. Record the OpenAPI schema, where available.
4. Record key endpoint responses, errors, auth outcomes, cache behavior, and timeout behavior.
5. Start the Docker Compose stack and run a smoke test.
6. Add characterization tests for Compare before moving either compare service.

### Phase 1 — create packages

1. Add \`modules/\`, \`platform/\`, \`shared/\`, and \`db/\` packages.
2. Add required \`__init__.py\` files.
3. Do not move behavior yet.
4. Confirm the app starts exactly as before.

### Phase 2 — move one feature at a time

Move in this order:

1. Notes
2. Spaces
3. Papers
4. Chat
5. Discovery
6. Compare

For each feature:

1. Move files only.
2. Update only imports and router registration.
3. Add temporary compatibility re-exports where necessary.
4. Run the feature's unit and API tests.
5. Smoke-test the unchanged public endpoint.
6. Commit the move separately.

### Phase 3 — move shared infrastructure

1. Move \`llm/\` to \`platform/llm/\`.
2. Consolidate \`retrieval/\` and \`vectorstore/\` into \`platform/retrieval/\`.
3. Move worker infrastructure to \`platform/jobs/\`.
4. Confirm task paths, queue names, and behavior remain unchanged.

### Phase 4 — consolidate only after stability

1. Audit compatibility shims.
2. Audit duplicate services, including the two Compare services.
3. Merge duplicates only with characterization tests that prove identical behavior.
4. Do not change prompts, model tiers, timeouts, cache keys, persistence, or UI behavior.

## Required verification after every move

Run:

~~~
Backend import and startup smoke test
Feature unit tests
Feature API tests
Migration test suite
Frontend lint, typecheck, and production build
Docker Compose startup smoke test
Manual test of unchanged public endpoint behavior
~~~

For Compare, specifically preserve and test:

~~~
Input validation
Paper ownership and space-pin checks
Saved-report cache behavior
Refresh behavior
Model-router fallback order
Timeout behavior
Report persistence
Verification fields and confidence behavior
HTTP status behavior, including 422, 404, and 504
~~~

## Test organization target

~~~
backend/tests/
├─ unit/
│  ├─ compare/
│  ├─ papers/
│  ├─ chat/
│  ├─ discovery/
│  └─ platform/
├─ integration/
│  ├─ database/
│  ├─ ollama/
│  └─ retrieval/
├─ api/
│  ├─ compare/
│  ├─ papers/
│  ├─ chat/
│  └─ spaces/
└─ fixtures/
~~~

Move tests with the corresponding feature only after they pass from the original location. A test-folder move must not alter fixtures, assertions, or intent.

## Explicitly out of scope

Do not, in this structure-only migration:

- replace Llama, Gemma, Qwen, embedding, or model-router configuration;
- activate the new evidence-ledger Compare workflow;
- change prompts, temperatures, seeds, retry counts, timeouts, or JSON parsing;
- change endpoints, payloads, error codes, or authentication;
- alter SQLAlchemy tables or unrelated migrations;
- change vector collections, embedding behavior, or cache keys;
- move user data without a data migration;
- rename frontend routes or redesign components;
- upgrade dependencies;
- remove old imports before verification.

## Completion criteria

The restructuring is complete only when:

- backend and frontend test suites pass;
- FastAPI starts from the same application entry point;
- public APIs preserve paths, contracts, status codes, and behavior;
- existing databases and Alembic migrations remain compatible;
- Docker Compose and workers start successfully;
- model routing, prompts, caching, and timeouts are unchanged;
- frontend behavior is unchanged;
- feature code is grouped under \`modules/<feature>/\`;
- shared adapters are under \`platform/\`;
- generated/runtime directories stay ignored;
- no user-visible functional or behavioral change has been introduced.

## Follow-up after this refactor

Only after the restructuring is stable, implement the grounded Compare roadmap as separate work:

1. source-bound evidence records;
2. typed fact extraction and validation;
3. deterministic numerical analysis;
4. grounded comparison and evidence suppression;
5. candidate gaps and conservative novelty checks;
6. background comparison jobs;
7. Qwen3/Qwen3-VL model rollout;
8. faculty-reviewed evaluation gates.

Keep the functional work separate so a regression can be attributed either to the structural refactor or to a deliberate product change, never both.
