import pytest

from app.api.routes import ingest as ingest_route


def test_ingest_endpoint_generates_initial_graph(client, user_headers):
    project = client.post(
        "/api/v1/projects",
        json={"name": "Ingest Case", "description": "Testing ingest"},
        headers=user_headers,
    ).json()["data"]

    response = client.post(
        "/api/v1/ingest",
        json={
            "project_id": project["id"],
            "raw_text": "Revenue is declining in our premium segment while acquisition costs are rising.",
        },
        headers=user_headers,
    )

    assert response.status_code == 201
    payload = response.json()["data"]
    assert payload["job"]["provider"] == "stub"
    assert payload["graph"]["nodes"]
    assert payload["graph"]["edges"]
    assert payload["graph"]["metadata"]["validation"]["is_valid"] is True


def test_ingest_endpoint_accepts_pdf_upload(client, user_headers, monkeypatch):
    pytest.importorskip("multipart")

    async def fake_extract_text_from_upload(upload):
        assert upload.filename == "case.pdf"
        return "Costs are rising while revenue growth is flattening across the core business."

    monkeypatch.setattr(ingest_route, "extract_text_from_upload", fake_extract_text_from_upload)

    project = client.post(
        "/api/v1/projects",
        json={"name": "PDF Ingest", "description": "Testing pdf ingest"},
        headers=user_headers,
    ).json()["data"]

    response = client.post(
        "/api/v1/ingest",
        data={"project_id": project["id"], "replace_existing": "false"},
        files={"file": ("case.pdf", b"%PDF-1.4 fake", "application/pdf")},
        headers=user_headers,
    )

    assert response.status_code == 201
    payload = response.json()["data"]
    assert payload["graph"]["nodes"]
    assert payload["job"]["provider"] == "stub"
