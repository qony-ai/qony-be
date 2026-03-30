# Qony AI Backend

FastAPI backend for Qony AI. The backend owns the canonical project/workspace graph, export transformation logic, and the backend-side trust boundary for authenticated requests coming from the Next.js frontend.

## What this backend owns

- project CRUD and canonical workspace creation
- ranked DAG persistence through `nodes`, `edges`, and workspace metadata
- graph validation for manual edits, ingest, export, and AI-assisted mutations
- export traversal and structured report model generation
- AI provider abstraction with `stub`, `ollama`, and `remote`
- signed frontend-to-backend actor validation
- structured logging, error envelopes, health endpoints, and Alembic migrations

## Auth contract

The frontend is the auth system of record. It authenticates the user with Better Auth, then forwards a short-lived signed bearer token to the backend.

Expected bearer claims:

- `sub`
  Better Auth user ID
- `email`
  Authenticated user email
- `name`
  Authenticated user name
- `plan`
  Effective viewer plan, currently `free` or `pro`
- `entitlements`
  Effective frontend entitlements

The backend maps `sub` onto `users.external_auth_id`.

Fallback behavior:

- `QONY_ALLOW_HEADER_ACTOR_FALLBACK=true` keeps old `X-User-*` header fallback available for local development
- `QONY_ALLOW_DEFAULT_ACTOR=true` allows a local default actor when no auth information is present
- both fallbacks should be disabled in staging/production

## Export behavior

`GET /api/v1/export/preview/{project_id}` now returns:

- legacy `chains`
- `report.summary`
- grouped report sections by Rank 2 sub-problem
- branch-level hypothesis / analysis / evidence / synthesis fields
- graph warnings and template metadata

The frontend uses this DTO to render the premium print-first report view.

## API surface

- `GET /health`
- `GET /ready`
- `GET /api/v1/projects`
- `POST /api/v1/projects`
- `GET /api/v1/projects/{project_id}`
- `PATCH /api/v1/projects/{project_id}`
- `DELETE /api/v1/projects/{project_id}`
- `POST /api/v1/ingest`
- `GET /api/v1/workspace/{project_id}`
- `PATCH /api/v1/workspace/mutate`
- `GET /api/v1/export/preview/{project_id}`

Successful responses use a `data` envelope. Errors use:

```json
{
  "error": {
    "code": "domain_validation_error",
    "message": "Workspace graph validation failed.",
    "details": {},
    "request_id": "..."
  }
}
```

## Domain rules

- non-empty workspaces must have exactly one Rank 1 problem statement
- rank transitions are strict and sequential: `1 -> 2 -> 3 -> 4 -> 5 -> 6`
- reverse edges are rejected
- cycles are rejected
- every non-root node must remain traceable to Rank 1
- Rank 4 nodes require a Rank 3 parent
- Rank 6 nodes must remain leaf-only
- export preview only includes complete branches that end in reachable Rank 6 nodes

## AI provider modes

Set `QONY_AI_PROVIDER` in `.env`.

- `stub`
  Deterministic local fallback
- `ollama`
  Uses `QONY_OLLAMA_BASE_URL` and `QONY_OLLAMA_MODEL`
- `remote`
  Uses `QONY_REMOTE_AI_BASE_URL`, `QONY_REMOTE_AI_API_KEY`, and `QONY_REMOTE_AI_MODEL`

If `QONY_AI_FALLBACK_TO_STUB=true`, provider failures fall back to the deterministic stub adapter.

## Local setup

1. Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

2. Start PostgreSQL:

```bash
docker compose up -d postgres
```

Manual Postgres also works. Create:

- database: `qony`
- user: `qony`
- password: `qony`

3. Copy env:

```bash
cp .env.example .env
```

Minimum values to confirm:

- `QONY_DATABASE_URL`
- `QONY_INTERNAL_ACTOR_SECRET`
- `QONY_INTERNAL_ACTOR_ISSUER`
- `QONY_INTERNAL_ACTOR_AUDIENCE`
- `QONY_AI_PROVIDER`

Local actor guidance:

- set `QONY_INTERNAL_ACTOR_SECRET` to the same shared secret used by the frontend as `QONY_INTERNAL_ACTOR_SECRET`
- keep `QONY_ALLOW_HEADER_ACTOR_FALLBACK=true` only for local migration/debugging
- keep `QONY_ALLOW_DEFAULT_ACTOR=true` only for local development

4. Run migrations:

```bash
alembic upgrade head
```

5. Start the backend:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Useful commands

Create a migration:

```bash
alembic revision --autogenerate -m "describe_change"
```

Run tests:

```bash
.venv/bin/pytest
```

Syntax check:

```bash
python3 -m compileall app alembic
```

Health checks:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/ready
```

Optional local header fallback request:

```bash
curl http://localhost:8000/api/v1/projects \
  -H "X-User-Email: you@example.com" \
  -H "X-User-Name: Your Name"
```

## Frontend integration notes

- server-side frontend fetches should use `QONY_API_BASE_URL`
- browser-side frontend fetches should use `NEXT_PUBLIC_API_BASE_URL`
- the frontend now forwards `Authorization: Bearer <internal_actor_token>`
- all workspace edits must go through `PATCH /api/v1/workspace/mutate`
- the canonical graph response shape remains:

```json
{
  "nodes": [],
  "edges": [],
  "metadata": {}
}
```

## Verification notes

Recommended local verification sequence:

1. Start Postgres.
2. Start the backend.
3. Start the frontend in `/Users/Shandy/Documents/Project/Qony-AI/qony-fe`.
4. Register a frontend user.
5. Confirm authenticated requests create or reuse a backend user with `external_auth_id`.
6. Open a project, build a complete branch, and verify `/export/preview/{projectId}` returns a structured report payload.
7. If Stripe is configured on the frontend, verify backend requests carry the expected `plan` and `entitlements` claims.
