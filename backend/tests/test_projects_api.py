from fastapi.testclient import TestClient

from app.main import app


def test_project_list_create_and_delete():
    client = TestClient(app)

    created = client.post("/api/projects", json={"name": "管理页测试 Agent"})
    assert created.status_code == 200
    project_id = created.json()["project"]["id"]

    listed = client.get("/api/projects")
    assert listed.status_code == 200
    assert any(item["id"] == project_id for item in listed.json())

    deleted = client.delete(f"/api/projects/{project_id}")
    assert deleted.status_code == 204


def test_project_run_preview():
    client = TestClient(app)

    created = client.post("/api/projects", json={"name": "运行预览测试 Agent"})
    assert created.status_code == 200
    project = created.json()
    project_id = project["project"]["id"]
    project["nodes"].extend(
        [
            {
                "id": "llm_1",
                "type": "llm",
                "label": "生成回答",
                "position": {"x": 320, "y": 220},
                "config": {"outputField": "final_answer"},
                "inputs": [{"id": "in", "type": "control", "label": "输入"}],
                "outputs": [{"id": "out", "type": "control", "label": "输出"}],
            },
            {
                "id": "reply_1",
                "type": "direct_reply",
                "label": "回复",
                "position": {"x": 560, "y": 220},
                "config": {"template": "{{ state.final_answer }}", "outputField": "final_answer"},
                "inputs": [{"id": "in", "type": "control", "label": "输入"}],
                "outputs": [],
            },
        ]
    )
    project["edges"].extend(
        [
            {"id": "e1", "source": "start", "sourceHandle": "out", "target": "llm_1", "kind": "normal"},
            {"id": "e2", "source": "llm_1", "sourceHandle": "out", "target": "reply_1", "kind": "normal"},
        ]
    )
    saved = client.put(f"/api/projects/{project_id}", json=project)
    assert saved.status_code == 200

    preview = client.post(f"/api/projects/{project_id}/run", json={"input": {"messages": "你好"}})
    assert preview.status_code == 200
    body = preview.json()
    assert body["mode"] == "dry"
    assert body["valid"] is True
    assert [item["nodeId"] for item in body["trace"]] == ["llm_1", "reply_1"]
    assert "final_answer" in body["outputState"]

    deleted = client.delete(f"/api/projects/{project_id}")
    assert deleted.status_code == 204
