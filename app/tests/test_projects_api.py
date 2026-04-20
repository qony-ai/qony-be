def test_project_crud_flow(client, user_headers):
    create_response = client.post(
        "/api/v1/projects",
        json={"name": "Market Entry", "description": "Assess new region"},
        headers=user_headers,
    )
    assert create_response.status_code == 201
    created = create_response.json()["data"]
    assert created["name"] == "Market Entry"
    assert created["graph_id"]

    list_response = client.get("/api/v1/projects", headers=user_headers)
    assert list_response.status_code == 200
    assert len(list_response.json()["data"]["items"]) == 1

    project_id = created["id"]
    get_response = client.get(f"/api/v1/projects/{project_id}", headers=user_headers)
    assert get_response.status_code == 200
    assert get_response.json()["data"]["id"] == project_id

    update_response = client.patch(
        f"/api/v1/projects/{project_id}",
        json={"status": "active", "name": "Market Entry Updated"},
        headers=user_headers,
    )
    assert update_response.status_code == 200
    assert update_response.json()["data"]["status"] == "active"
    assert update_response.json()["data"]["name"] == "Market Entry Updated"

    delete_response = client.delete(f"/api/v1/projects/{project_id}", headers=user_headers)
    assert delete_response.status_code == 200
    assert delete_response.json()["data"]["deleted"] is True

    final_list = client.get("/api/v1/projects", headers=user_headers)
    assert final_list.status_code == 200
    assert final_list.json()["data"]["items"] == []


def test_local_mode_can_access_existing_projects_without_user_headers(client, user_headers):
    created = client.post(
        "/api/v1/projects",
        json={"name": "Shared Access", "description": "Local mode access"},
        headers=user_headers,
    ).json()["data"]

    list_response = client.get("/api/v1/projects")
    assert list_response.status_code == 200
    ids = {item["id"] for item in list_response.json()["data"]["items"]}
    assert created["id"] in ids

    get_response = client.get(f"/api/v1/projects/{created['id']}")
    assert get_response.status_code == 200
    assert get_response.json()["data"]["id"] == created["id"]
