from pathlib import Path

from app.services.export_engine import ExportEngine


def test_export_preview_returns_real_slide_plan(client, user_headers):
    project = client.post(
        "/api/v1/projects",
        json={"name": "Export Case", "description": "Structured export preview"},
        headers=user_headers,
    ).json()["data"]

    ingest_response = client.post(
        "/api/v1/ingest",
        json={
            "project_id": project["id"],
            "raw_text": (
                "Customer retention is slipping in the premium segment. "
                "Blanket promotions are hurting margin recovery."
            ),
        },
        headers=user_headers,
    )
    assert ingest_response.status_code == 201

    response = client.get(
        f"/api/v1/export/preview/{project['id']}?deliverable_type=business_document",
        headers=user_headers,
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["status"] == "ready"
    assert payload["deliverable_type"] == "business_document"
    assert payload["project_name"] == "Export Case"
    assert payload["manifest_version"]
    assert payload["slide_plan"] is not None
    assert payload["slide_plan"]["steps"]
    assert payload["slide_plan"]["steps"][0]["component_key"].startswith("business_document.")


def test_export_job_generates_downloadable_pdf(client, user_headers, monkeypatch):
    def fake_render_pdf_file(
        self,
        *,
        html_path: Path,
        pdf_path: Path,
        deliverable_type: str,
    ) -> None:
        assert html_path.exists()
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.write_bytes(
            b"%PDF-1.4\n%Qony test export\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF"
        )

    monkeypatch.setattr(ExportEngine, "_render_pdf_file", fake_render_pdf_file)

    project = client.post(
        "/api/v1/projects",
        json={"name": "Export PDF", "description": "Deck export verification"},
        headers=user_headers,
    ).json()["data"]

    ingest_response = client.post(
        "/api/v1/ingest",
        json={
            "project_id": project["id"],
            "raw_text": (
                "Traffic is growing but basket quality is deteriorating. "
                "We need a more targeted growth strategy."
            ),
        },
        headers=user_headers,
    )
    assert ingest_response.status_code == 201

    create_response = client.post(
        "/api/v1/export/jobs",
        json={
            "project_id": project["id"],
            "deliverable_type": "pitch_deck",
        },
        headers=user_headers,
    )

    assert create_response.status_code == 200
    job = create_response.json()["data"]
    assert job["status"] == "completed"
    assert job["pdf_artifact_path"]
    assert job["slide_plan"] is not None

    job_response = client.get(
        f"/api/v1/export/jobs/{job['id']}",
        headers=user_headers,
    )
    assert job_response.status_code == 200
    assert job_response.json()["data"]["status"] == "completed"

    pdf_response = client.get(
        f"/api/v1/export/jobs/{job['id']}/pdf",
        headers=user_headers,
    )
    assert pdf_response.status_code == 200
    assert pdf_response.headers["content-type"] == "application/pdf"
    assert pdf_response.content.startswith(b"%PDF-1.4")
