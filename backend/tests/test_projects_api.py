from fastapi.testclient import TestClient

import app.api.workspace as workspace_api
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

    preview = client.post(
        f"/api/projects/{project_id}/run",
        json={
            "input": {"messages": "你好"},
            "modelConfig": {
                "name": "OpenAI 测试",
                "provider": "openai",
                "model": "gpt-4.1-mini",
                "apiKeyEnv": "OPENAI_API_KEY",
                "enabled": True,
            },
        },
    )
    assert preview.status_code == 200
    body = preview.json()
    assert body["mode"] == "dry"
    assert body["valid"] is True
    assert [item["nodeId"] for item in body["trace"]] == ["llm_1", "reply_1"]
    assert "final_answer" in body["outputState"]

    deleted = client.delete(f"/api/projects/{project_id}")
    assert deleted.status_code == 204


def test_workspace_model_configs_are_persisted(tmp_path, monkeypatch):
    models_file = tmp_path / "models.json"
    monkeypatch.setattr(workspace_api, "WORKSPACE_MODELS_FILE", models_file)
    client = TestClient(app)

    payload = [
        {
            "id": "model_test_1",
            "name": "DeepSeek 测试",
            "provider": "deepseek",
            "model": "deepseek-chat",
            "baseUrl": "https://api.deepseek.com",
            "apiKey": "sk-test",
            "apiKeyEnv": "",
            "apiVersion": "",
            "organization": "",
            "homepage": "https://www.deepseek.com",
            "apiFormat": "openai_compatible",
            "extraOptionsJson": "{}",
            "modelRowsJson": '[{"id":"deepseek-chat","name":"DeepSeek Chat"}]',
            "modelsJson": '{"deepseek-chat":{"name":"DeepSeek Chat"}}',
            "enabled": True,
            "isDefault": False,
            "notes": "本地测试",
        },
        {
            "id": "model_test_2",
            "name": "Qwen 测试",
            "provider": "qwen",
            "model": "qwen-plus",
            "baseUrl": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "apiKey": "",
            "apiKeyEnv": "DASHSCOPE_API_KEY",
            "apiVersion": "",
            "organization": "",
            "homepage": "",
            "apiFormat": "openai_compatible",
            "extraOptionsJson": "{}",
            "modelRowsJson": '[{"id":"qwen-plus","name":"Qwen Plus"}]',
            "modelsJson": '{"qwen-plus":{"name":"Qwen Plus"}}',
            "enabled": True,
            "isDefault": True,
            "notes": "",
        },
    ]

    saved = client.put("/api/workspace/models", json=payload)
    assert saved.status_code == 200
    body = saved.json()
    assert models_file.exists()
    assert [item["id"] for item in body] == ["model_test_1", "model_test_2"]
    assert [item["isDefault"] for item in body] == [False, True]

    listed = client.get("/api/workspace/models")
    assert listed.status_code == 200
    assert listed.json() == body


def test_workspace_tools_and_mcp_are_persisted(tmp_path, monkeypatch):
    tools_file = tmp_path / "tools.json"
    mcp_file = tmp_path / "mcp_servers.json"
    monkeypatch.setattr(workspace_api, "WORKSPACE_TOOLS_FILE", tools_file)
    monkeypatch.setattr(workspace_api, "WORKSPACE_MCP_FILE", mcp_file)
    client = TestClient(app)

    tools_payload = [
        {
            "id": "tool_lookup",
            "name": "订单查询",
            "description": "查询订单状态",
            "source": "http",
            "schemaJson": "{\"type\":\"object\"}",
        }
    ]
    saved_tools = client.put("/api/workspace/tools", json=tools_payload)
    assert saved_tools.status_code == 200
    assert tools_file.exists()
    assert saved_tools.json()[0]["name"] == "订单查询"
    assert client.get("/api/workspace/tools").json() == saved_tools.json()

    mcp_payload = [
        {
            "id": "mcp_docs",
            "name": "文档 MCP",
            "transport": "stdio",
            "command": "python -m docs_mcp",
            "url": "",
            "description": "本地文档工具",
        }
    ]
    saved_mcp = client.put("/api/workspace/mcp", json=mcp_payload)
    assert saved_mcp.status_code == 200
    assert mcp_file.exists()
    assert saved_mcp.json()[0]["command"] == "python -m docs_mcp"
    assert client.get("/api/workspace/mcp").json() == saved_mcp.json()


def test_workspace_rag_knowledge_bases_are_persisted(tmp_path, monkeypatch):
    rag_file = tmp_path / "rag_knowledge_bases.json"
    monkeypatch.setattr(workspace_api, "WORKSPACE_RAG_FILE", rag_file)
    client = TestClient(app)

    payload = [
        {
            "id": "rag_local_docs",
            "name": "产品文档",
            "sourceType": "local_directory",
            "path": "./knowledge/product",
            "url": "",
            "collection": "",
            "description": "产品说明和 FAQ",
            "embeddingModel": "bge-m3",
            "topK": 5,
            "metadataJson": "{\"domain\":\"product\"}",
            "enabled": True,
        },
        {
            "id": "rag_http_search",
            "name": "外部检索",
            "sourceType": "http_api",
            "path": "",
            "url": "https://api.example.com/search",
            "collection": "support",
            "description": "",
            "embeddingModel": "",
            "topK": 0,
            "metadataJson": "",
            "enabled": False,
        },
    ]

    saved = client.put("/api/workspace/rag", json=payload)
    assert saved.status_code == 200
    body = saved.json()
    assert rag_file.exists()
    assert [item["id"] for item in body] == ["rag_local_docs", "rag_http_search"]
    assert body[0]["topK"] == 5
    assert body[1]["topK"] == 4
    assert body[1]["metadataJson"] == "{}"

    listed = client.get("/api/workspace/rag")
    assert listed.status_code == 200
    assert listed.json() == body
