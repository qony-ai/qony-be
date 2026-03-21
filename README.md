# Qony AI Backend

Production-ready FastAPI backend for Qony AI. The backend persists the canonical workspace graph in PostgreSQL, validates ranked DAG mutations before commit, and exposes typed API contracts for the Next.js frontend.

## What This Backend Owns

- Project CRUD and canonical workspace creation
- Ranked DAG persistence through `nodes`, `edges`, and workspace metadata
- Reusable graph validation for manual, ingest, export, and AI-assisted mutations
- AI provider abstraction with `stub`, `ollama`, and `remote` adapters
- Export preview traversal over complete Rank 1 to Rank 6 branches
- Structured logging, error envelopes, health endpoints, and Alembic migrations

## Folder Structure

```text
qony-be/
  app/
    api/
      deps.py
      error_handlers.py
      middleware.py
      routes/
    core/
    db/
    domain/
    integrations/ai/
    models/
    repositories/
    schemas/
    services/
    tests/
  alembic/
  docker-compose.yml
  alembic.ini
  pyproject.toml
  .env.example
```

## Domain Rules

- Non-empty workspaces must have exactly one Rank 1 problem statement.
- Rank transitions are strict and sequential: `1->2->3->4->5->6`.
- Reverse edges are rejected.
- Cycles are rejected.
- Every non-root node must remain traceable to Rank 1.
- Rank 4 nodes require a Rank 3 parent.
- Rank 6 nodes must remain leaf-only.
- Export preview only includes complete branches that end in reachable Rank 6 nodes.

## API Surface

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

## AI Provider Modes

Set `QONY_AI_PROVIDER` in `.env`.

- `stub`
  Deterministic local fallback. Recommended for initial local setup and tests.
- `ollama`
  Uses `QONY_OLLAMA_BASE_URL` and `QONY_OLLAMA_MODEL`.
- `remote`
  Uses `QONY_REMOTE_AI_BASE_URL`, `QONY_REMOTE_AI_API_KEY`, and `QONY_REMOTE_AI_MODEL` against an OpenAI-compatible chat completions API.

If `QONY_AI_FALLBACK_TO_STUB=true`, provider failures fall back to the deterministic stub adapter.

## Local Setup

### 1. Create and activate a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 2. Start PostgreSQL

Docker Compose:

```bash
docker compose up -d postgres
```

Manual Postgres is also fine. Create:

- database: `qony`
- user: `qony`
- password: `qony`

Then set `QONY_DATABASE_URL` accordingly.

### 3. Configure environment

```bash
cp .env.example .env
```

Minimum values to confirm:

- `QONY_DATABASE_URL`
- `QONY_AI_PROVIDER`
- `QONY_REMOTE_AI_API_KEY` only for `remote`
- `QONY_OLLAMA_BASE_URL` and `QONY_OLLAMA_MODEL` only for `ollama`

### 4. Run migrations

```bash
alembic upgrade head
```

### 5. Start the backend

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Useful Commands

Create a migration:

```bash
alembic revision --autogenerate -m "describe_change"
```

Run tests:

```bash
pytest
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

## Frontend Integration Notes

- Server-side frontend fetches should use `QONY_API_BASE_URL`.
- Browser-side frontend fetches should use `NEXT_PUBLIC_API_BASE_URL`.
- The canonical graph response shape is always:

```json
{
  "nodes": [],
  "edges": [],
  "metadata": {}
}
```

- All workspace edits must go through `PATCH /api/v1/workspace/mutate`.

## Sample Developer Runbook

1. Start Postgres.
2. Install backend dependencies.
3. Copy `.env.example` to `.env`.
4. Run `alembic upgrade head`.
5. Start the backend.
6. Start the frontend in `qony-fe`.
7. Create a project in `/dashboard`.
8. Ingest raw text in `/project/ingest`.
9. Open `/workspace/{projectId}` and mutate the graph.
10. Open `/export/preview/{projectId}` and confirm complete branches appear.

## Verification Notes

In this workspace, Python runtime dependencies were not installed, so FastAPI/pytest execution was not run locally. The backend code was syntax-checked with `python3 -m compileall app alembic`.
