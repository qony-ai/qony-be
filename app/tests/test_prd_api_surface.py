from __future__ import annotations

import io
from time import sleep

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User


def test_auth_register_and_login(client):
    register_response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "auth-user@qony.ai",
            "name": "Auth User",
            "password": "supersecure123",
        },
    )
    assert register_response.status_code == 201
    register_payload = register_response.json()["data"]
    assert register_payload["user"]["email"] == "auth-user@qony.ai"
    assert register_payload["tokens"]["access_token"]

    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "auth-user@qony.ai",
            "password": "supersecure123",
        },
    )
    assert login_response.status_code == 200
    login_payload = login_response.json()["data"]
    assert login_payload["user"]["name"] == "Auth User"
    assert login_payload["tokens"]["refresh_token"]


def test_prd_graph_crud_ai_edit_and_export(client, user_headers):
    project_response = client.post(
        "/api/v1/projects",
        json={"name": "PRD Graph Project", "description": "Graph CRUD"},
        headers=user_headers,
    )
    assert project_response.status_code == 201
    graph_id = project_response.json()["data"]["graph_id"]

    node_one = client.post(
        f"/api/v1/nodes/{graph_id}",
        json={
            "type": "problem",
            "title": "Customer churn is rising",
            "description": "Retention declined across the last quarter.",
            "source": "document",
            "position": {"x": 0, "y": 0},
        },
        headers=user_headers,
    )
    assert node_one.status_code == 201
    node_one_id = node_one.json()["data"]["id"]

    node_two = client.post(
        f"/api/v1/nodes/{graph_id}",
        json={
            "type": "solution",
            "title": "Launch save offer experiment",
            "description": "Test targeted save offers for high-risk accounts.",
            "source": "user",
            "position": {"x": 320, "y": 0},
        },
        headers=user_headers,
    )
    assert node_two.status_code == 201
    node_two_id = node_two.json()["data"]["id"]

    edge_response = client.post(
        f"/api/v1/edges/{graph_id}",
        json={
            "source": node_one_id,
            "target": node_two_id,
            "relation_type": "supports",
            "metadata": {},
        },
        headers=user_headers,
    )
    assert edge_response.status_code == 201

    graph_response = client.get(f"/api/v1/graphs/{graph_id}", headers=user_headers)
    assert graph_response.status_code == 200
    graph_payload = graph_response.json()["data"]
    assert len(graph_payload["nodes"]) == 2
    assert len(graph_payload["edges"]) == 1

    ai_edit_response = client.post(
        f"/api/v1/graphs/{graph_id}/ai-edit",
        json={"prompt": "Add risk: discounting may reduce margin quality"},
        headers=user_headers,
    )
    assert ai_edit_response.status_code == 200
    assert len(ai_edit_response.json()["data"]["graph"]["nodes"]) >= 3

    export_response = client.post(
        f"/api/v1/graphs/{graph_id}/export",
        json={"export_type": "pitch_deck"},
        headers=user_headers,
    )
    assert export_response.status_code == 200
    export_job_id = export_response.json()["data"]["id"]

    export_job_response = client.get(f"/api/v1/exports/{export_job_id}", headers=user_headers)
    assert export_job_response.status_code == 200
    assert export_job_response.json()["data"]["status"] == "completed"
    assert export_job_response.json()["data"]["output_url"]


def test_prd_ingestion_progress_and_admin_endpoints(client, app, user_headers):
    project_response = client.post(
        "/api/v1/projects",
        json={"name": "PRD Ingestion Project", "description": "Ingestion flow"},
        headers=user_headers,
    )
    assert project_response.status_code == 201
    project_id = project_response.json()["data"]["id"]

    upload_response = client.post(
        f"/api/v1/projects/{project_id}/ingest",
        headers=user_headers,
        files={"file": ("case.txt", io.BytesIO(b"Problem: revenue declined.\nSolution: improve retention.\nMetric: retention rate."), "text/plain")},
    )
    assert upload_response.status_code == 202
    assert upload_response.json()["data"]["graph_id"]
    job_id = upload_response.json()["data"]["id"]

    with client.websocket_connect(f"/api/v1/ws/ingest/{job_id}") as websocket:
        final_event = None
        for _ in range(8):
            event = websocket.receive_json()
            final_event = event
            if event.get("event") == "complete":
                break
        assert final_event is not None
        assert final_event["event"] == "complete"
        assert int(final_event["node_count"]) >= 1

    metrics_forbidden = client.get("/api/v1/admin/metrics", headers=user_headers)
    assert metrics_forbidden.status_code == 403

    with Session(app.state.engine) as session:
        user = session.scalar(select(User).where(User.email == "tester@qony.ai"))
        assert user is not None
        user.role = "admin"
        session.commit()

    metrics_response = client.get("/api/v1/admin/metrics", headers=user_headers)
    assert metrics_response.status_code == 200
    flags_response = client.get("/api/v1/admin/flags", headers=user_headers)
    assert flags_response.status_code == 200
    assert flags_response.json()["data"]["items"]
