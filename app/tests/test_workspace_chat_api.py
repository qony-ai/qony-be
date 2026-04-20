from app.domain.enums import NodeType


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
    nodes = first_payload["graph"]["nodes"]
    assert len(nodes) == 1
    assert nodes[0]["type"] == NodeType.ASSUMPTION.value
    assert first_payload["graph"]["metadata"]["version"] == 2
    assert first_payload["applied_commands"] == ["add_node"]
    assert first_payload["ai_commands_applied"] == 1
    assert len(first_payload["chat"]["messages"]) == 2
    assert first_payload["chat"]["messages"][0]["role"] == "user"
    assert first_payload["chat"]["messages"][1]["role"] == "assistant"
    assert first_payload["assistant_message"]["content"]
    assert first_payload["assistant_message"]["metadata"]["action"] == "rewrite_graph"

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
    assert "add_node" in second_payload["applied_commands"]
    assert "add_edge" in second_payload["applied_commands"]
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
