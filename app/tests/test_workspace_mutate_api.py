from uuid import uuid4


def test_workspace_mutate_can_add_node_and_edge_for_branching(client, user_headers):
    project = client.post(
        "/api/v1/projects",
        json={"name": "Workspace Mutate", "description": "Manual mutation flow"},
        headers=user_headers,
    ).json()["data"]

    initial_workspace = client.get(
        f"/api/v1/workspace/{project['id']}",
        headers=user_headers,
    )
    assert initial_workspace.status_code == 200
    initial_payload = initial_workspace.json()["data"]
    version = initial_payload["graph"]["metadata"]["version"]

    add_root_response = client.patch(
        "/api/v1/workspace/mutate",
        json={
            "project_id": project["id"],
            "expected_version": version,
            "actor": "user",
            "reason": "Add root node",
            "commands": [
                {
                    "type": "add_node",
                    "node": {
                        "rank": 1,
                        "title": "Problem",
                        "content": "Primary problem statement",
                        "source": "manual",
                        "position": {"x": 0, "y": 0},
                        "metadata": {},
                    },
                }
            ],
        },
        headers=user_headers,
    )

    assert add_root_response.status_code == 200
    root_payload = add_root_response.json()["data"]
    version = root_payload["graph"]["metadata"]["version"]
    root_id = root_payload["graph"]["nodes"][0]["id"]

    first_child_id = str(uuid4())
    second_child_id = str(uuid4())

    add_children_response = client.patch(
        "/api/v1/workspace/mutate",
        json={
            "project_id": project["id"],
            "expected_version": version,
            "actor": "user",
            "reason": "Add branching children and connect them",
            "commands": [
                {
                    "type": "add_node",
                    "node": {
                        "id": first_child_id,
                        "rank": 2,
                        "title": "Child A",
                        "content": "First branch",
                        "source": "manual",
                        "position": {"x": 340, "y": 0},
                        "metadata": {"branch_index": 0},
                    },
                },
                {
                    "type": "add_node",
                    "node": {
                        "id": second_child_id,
                        "rank": 2,
                        "title": "Child B",
                        "content": "Second branch",
                        "source": "manual",
                        "position": {"x": 340, "y": 240},
                        "metadata": {"branch_index": 1},
                    },
                },
                {
                    "type": "add_edge",
                    "edge": {
                        "source": root_id,
                        "target": first_child_id,
                    },
                },
                {
                    "type": "add_edge",
                    "edge": {
                        "source": root_id,
                        "target": second_child_id,
                    },
                },
            ],
        },
        headers=user_headers,
    )

    assert add_children_response.status_code == 200
    payload = add_children_response.json()["data"]
    assert payload["graph"]["metadata"]["validation"]["is_valid"] is True
    assert len(payload["graph"]["edges"]) == 2
    assert len([edge for edge in payload["graph"]["edges"] if edge["source"] == root_id]) == 2
