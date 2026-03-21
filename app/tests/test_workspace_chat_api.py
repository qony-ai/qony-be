from app.domain.enums import NodeRank


def test_workspace_chat_mutates_graph_and_persists_chat_history(client, user_headers):
    project = client.post(
        "/api/v1/projects",
        json={"name": "Workspace Chat", "description": "AI chat mutation flow"},
        headers=user_headers,
    ).json()["data"]

    initial_workspace = client.get(
        f"/api/v1/workspace/{project['id']}",
        headers=user_headers,
    )
    assert initial_workspace.status_code == 200
    assert initial_workspace.json()["data"]["chat"]["messages"] == []
    assert initial_workspace.json()["data"]["graph"]["nodes"] == []

    first_chat = client.post(
        "/api/v1/workspace/chat",
        json={
            "project_id": project["id"],
            "expected_version": initial_workspace.json()["data"]["graph"]["metadata"]["version"],
            "message": "Define the main inventory control problem for this workspace.",
        },
        headers=user_headers,
    )

    assert first_chat.status_code == 200
    first_payload = first_chat.json()["data"]
    assert len(first_payload["graph"]["nodes"]) == 1
    assert first_payload["graph"]["nodes"][0]["rank"] == NodeRank.PROBLEM_STATEMENT
    assert first_payload["graph"]["metadata"]["version"] == 2
    assert first_payload["applied_commands"] == ["add_node"]
    assert first_payload["ai_commands_applied"] == 1
    assert len(first_payload["chat"]["messages"]) == 2
    assert first_payload["chat"]["messages"][0]["role"] == "user"
    assert first_payload["chat"]["messages"][1]["role"] == "assistant"
    assert first_payload["assistant_message"]["content"]
    assert first_payload["assistant_message"]["metadata"]["action"] == "rewrite_graph"
    assert first_payload["assistant_message"]["metadata"]["request_payload"]["request"]
    assert first_payload["assistant_message"]["metadata"]["response_payload"]["graph"]["nodes"]

    second_chat = client.post(
        "/api/v1/workspace/chat",
        json={
            "project_id": project["id"],
            "expected_version": first_payload["graph"]["metadata"]["version"],
            "message": "Add a sub-problem about stockout on fast-moving items.",
        },
        headers=user_headers,
    )

    assert second_chat.status_code == 200
    second_payload = second_chat.json()["data"]
    assert len(second_payload["graph"]["nodes"]) == 2
    assert len(second_payload["graph"]["edges"]) == 1
    assert second_payload["graph"]["metadata"]["version"] == 3
    assert second_payload["ai_commands_applied"] == 2
    assert second_payload["applied_commands"] == ["add_node", "add_edge"]
    assert len(second_payload["chat"]["messages"]) == 4
    assert second_payload["chat"]["messages"][-1]["role"] == "assistant"
    assert second_payload["assistant_message"]["graph_version"] == 3

    refreshed_workspace = client.get(
        f"/api/v1/workspace/{project['id']}",
        headers=user_headers,
    )

    assert refreshed_workspace.status_code == 200
    refreshed_payload = refreshed_workspace.json()["data"]
    assert len(refreshed_payload["chat"]["messages"]) == 4
    assert refreshed_payload["chat"]["messages"][-1]["content"] == second_payload["assistant_message"]["content"]
    assert refreshed_payload["graph"]["metadata"]["version"] == 3


def test_workspace_chat_can_explain_without_mutating_graph(client, user_headers):
    project = client.post(
        "/api/v1/projects",
        json={"name": "Workspace Explain", "description": "Explain only flow"},
        headers=user_headers,
    ).json()["data"]

    ingest_response = client.post(
        "/api/v1/ingest",
        json={
            "project_id": project["id"],
            "raw_text": "Revenue is declining while stockout on fast-moving items is increasing.",
        },
        headers=user_headers,
    )
    assert ingest_response.status_code == 201
    version_before = ingest_response.json()["data"]["graph"]["metadata"]["version"]

    response = client.post(
        "/api/v1/workspace/chat",
        json={
            "project_id": project["id"],
            "expected_version": version_before,
            "message": "Jelaskan fungsi rank 4 pada graph ini?",
        },
        headers=user_headers,
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["graph"]["metadata"]["version"] == version_before
    assert payload["applied_commands"] == []
    assert payload["ai_commands_applied"] == 0
    assert payload["assistant_message"]["metadata"]["action"] == "explain"
    assert "Rank 4 berfungsi" in payload["assistant_message"]["content"]


def test_workspace_chat_can_explain_case_overview_without_mutating_graph(client, user_headers):
    project = client.post(
        "/api/v1/projects",
        json={"name": "Workspace Explain Overview", "description": "Explain overview flow"},
        headers=user_headers,
    ).json()["data"]

    ingest_response = client.post(
        "/api/v1/ingest",
        json={
            "project_id": project["id"],
            "raw_text": """
            BUSINESS CASE
            Implementasi Sistem Inventory & Procurement Digital
            1. Latar belakang & masalah
            - Stockout pada item fast-moving menyebabkan lost sales.
            - Tim operasional menghabiskan banyak waktu untuk rekonsiliasi data stok.
            - Pembelian darurat meningkatkan biaya logistik.
            """,
        },
        headers=user_headers,
    )
    assert ingest_response.status_code == 201
    version_before = ingest_response.json()["data"]["graph"]["metadata"]["version"]

    response = client.post(
        "/api/v1/workspace/chat",
        json={
            "project_id": project["id"],
            "expected_version": version_before,
            "message": "Jelaskan case secara keseluruhan.",
        },
        headers=user_headers,
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["graph"]["metadata"]["version"] == version_before
    assert payload["applied_commands"] == []
    assert payload["assistant_message"]["metadata"]["action"] == "explain"
    assert "Sub-problem utamanya" in payload["assistant_message"]["content"]
    assert "Graph tidak diubah" in payload["assistant_message"]["content"]


def test_workspace_chat_can_remove_rank_branch_via_full_graph_rewrite(client, user_headers):
    project = client.post(
        "/api/v1/projects",
        json={"name": "Workspace Delete Rank", "description": "Delete rank flow"},
        headers=user_headers,
    ).json()["data"]

    ingest_response = client.post(
        "/api/v1/ingest",
        json={
            "project_id": project["id"],
            "raw_text": """
            BUSINESS CASE
            Implementasi Sistem Inventory & Procurement Digital
            1. Latar belakang & masalah
            - Stockout pada item fast-moving menyebabkan lost sales.
            - Tim operasional menghabiskan banyak waktu untuk rekonsiliasi data stok.
            - Pembelian darurat meningkatkan biaya logistik.
            """,
        },
        headers=user_headers,
    )
    assert ingest_response.status_code == 201
    version_before = ingest_response.json()["data"]["graph"]["metadata"]["version"]

    response = client.post(
        "/api/v1/workspace/chat",
        json={
            "project_id": project["id"],
            "expected_version": version_before,
            "message": "Hapus semua nodes rank 4 dari graph ini.",
        },
        headers=user_headers,
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    remaining_ranks = {node["rank"] for node in payload["graph"]["nodes"]}
    assert 4 not in remaining_ranks
    assert 5 not in remaining_ranks
    assert 6 not in remaining_ranks
    assert "delete_node" in payload["applied_commands"]
    assert payload["assistant_message"]["metadata"]["action"] == "rewrite_graph"
