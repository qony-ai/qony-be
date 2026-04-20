# Qony Backend

FastAPI backend for the Qony Business Case Intelligence Platform.

## Active PRD endpoints

- `POST /api/v1/auth/register`
- `POST /api/v1/auth/login`
- `POST /api/v1/auth/refresh`
- `GET /api/v1/projects`
- `POST /api/v1/projects`
- `GET /api/v1/projects/{project_id}`
- `PATCH /api/v1/projects/{project_id}`
- `DELETE /api/v1/projects/{project_id}`
- `GET /api/v1/projects/{project_id}/graph`
- `POST /api/v1/projects/{project_id}/ingest`
- `WS /api/v1/ws/ingest/{job_id}`
- `GET /api/v1/graphs/{graph_id}`
- `PUT /api/v1/graphs/{graph_id}`
- `POST /api/v1/graphs/{graph_id}/ai-edit`
- `POST /api/v1/graphs/{graph_id}/export`
- `POST /api/v1/nodes/{graph_id}`
- `PATCH /api/v1/nodes/{node_id}`
- `DELETE /api/v1/nodes/{node_id}`
- `POST /api/v1/edges/{graph_id}`
- `PATCH /api/v1/edges/{edge_id}`
- `DELETE /api/v1/edges/{edge_id}`
- `GET /api/v1/exports/{job_id}`
- `POST /api/v1/payment/checkout`
- `GET /api/v1/payment/subscription`
- `POST /api/v1/payment/webhook/midtrans`
- `GET /api/v1/admin/users`
- `GET /api/v1/admin/metrics`
- `GET /api/v1/admin/flags`

## Implementation notes

- All AI calls go through `app/services/ai_router.py`.
- Ingestion runs document extraction and web enrichment in parallel.
- Web enrichment failures do not cancel document extraction.
- Typed graph nodes use `type`, never `rank`, `priority`, `level`, or `order`.
- Web-derived nodes must keep `source="web"`, `is_enrichment=true`, and `source_url`.
- Export planning is AI-driven from graph data plus the component manifest.
- Midtrans webhook processing verifies the request signature before mutating subscription state.
- Usage metering records uploads, scraping, AI edits, and exports.

## Run locally

```bash
./.venv/bin/pip install -r requirements.txt
./.venv/bin/uvicorn app.main:app --reload
```

## Verify

```bash
./.venv/bin/pytest -q
```
