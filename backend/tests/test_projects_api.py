import json
from pathlib import Path

from fastapi.testclient import TestClient

import app.config as app_config
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


def test_runtime_env_loads_root_env_file(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text(
        """
        MIMO_API_KEY=env-file-token
        EXISTING_KEY=from-env-file
        QUOTED_VALUE="quoted token"
        # ignored
        """,
        encoding="utf-8",
    )
    monkeypatch.setattr(app_config, "ROOT_DIR", tmp_path)
    monkeypatch.delenv("MIMO_API_KEY", raising=False)
    monkeypatch.setenv("EXISTING_KEY", "from-process")
    monkeypatch.delenv("QUOTED_VALUE", raising=False)

    app_config.load_runtime_env()

    assert app_config.os.getenv("MIMO_API_KEY") == "env-file-token"
    assert app_config.os.getenv("EXISTING_KEY") == "from-process"
    assert app_config.os.getenv("QUOTED_VALUE") == "quoted token"


def test_workspace_env_check_reports_loaded_variable(monkeypatch):
    monkeypatch.setenv("MIMO_API_KEY", "test-token")
    client = TestClient(app)

    found = client.post("/api/workspace/env/check", json={"name": "MIMO_API_KEY"})
    invalid = client.post("/api/workspace/env/check", json={"name": "tp-not-a-variable"})

    assert found.status_code == 200
    assert found.json()["exists"] is True
    assert found.json()["length"] == len("test-token")
    assert invalid.status_code == 200
    assert invalid.json()["valid"] is False


def test_project_run_preview():
    client = TestClient(app)

    created = client.post("/api/projects", json={"name": "运行预览测试 Agent"})
    assert created.status_code == 200
    project = created.json()
    project_id = project["project"]["id"]
    project["state"]["fields"].append({"name": "final_answer", "type": "str", "description": ""})
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


def test_project_run_stream_emits_node_events():
    client = TestClient(app)

    created = client.post("/api/projects", json={"name": "流式运行测试 Agent"})
    assert created.status_code == 200
    project = created.json()
    project_id = project["project"]["id"]
    project["state"]["fields"].append({"name": "final_answer", "type": "str", "description": ""})
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
    assert client.put(f"/api/projects/{project_id}", json=project).status_code == 200

    with client.stream(
        "POST",
        f"/api/projects/{project_id}/run/stream",
        json={"input": {"messages": "你好"}, "mode": "dry"},
    ) as response:
        assert response.status_code == 200
        events = [json.loads(line) for line in response.iter_lines() if line]

    assert [event["event"] for event in events] == [
        "run_start",
        "node_start",
        "node_end",
        "node_start",
        "node_end",
        "run_end",
    ]
    assert events[1]["nodeId"] == "llm_1"
    assert events[2]["traceItem"]["outputDelta"]["final_answer"].startswith("[dry-run]")
    assert events[-1]["outputState"]["final_answer"]

    deleted = client.delete(f"/api/projects/{project_id}")
    assert deleted.status_code == 204


def test_project_save_and_read_preserves_skills():
    client = TestClient(app)

    created = client.post("/api/projects", json={"name": "Skills 保存测试 Agent"})
    assert created.status_code == 200
    project = created.json()
    project_id = project["project"]["id"]
    project["skills"] = [
        {
            "id": "skill_tone",
            "name": "语气控制",
            "description": "控制客服语气",
            "sourceType": "manual",
            "sourcePath": "",
            "filePath": "",
            "content": "请保持礼貌、简洁。",
            "metadataJson": "{}",
            "enabled": True,
        }
    ]

    saved = client.put(f"/api/projects/{project_id}", json=project)
    assert saved.status_code == 200
    assert saved.json()["skills"][0]["name"] == "语气控制"

    loaded = client.get(f"/api/projects/{project_id}")
    assert loaded.status_code == 200
    assert loaded.json()["skills"][0]["content"] == "请保持礼貌、简洁。"

    deleted = client.delete(f"/api/projects/{project_id}")
    assert deleted.status_code == 204


def test_project_export_returns_smoke_test_result():
    client = TestClient(app)

    created = client.post("/api/projects", json={"name": "导出测试 Agent"})
    assert created.status_code == 200
    project = created.json()
    project_id = project["project"]["id"]
    project["state"]["fields"].append({"name": "final_answer", "type": "str", "description": ""})
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
    assert client.put(f"/api/projects/{project_id}", json=project).status_code == 200

    exported = client.post(f"/api/projects/{project_id}/export")
    assert exported.status_code == 200
    body = exported.json()
    assert body["smokeTest"]["passed"] is True
    assert "tests/test_graph_smoke.py" in body["files"]

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
            "apiKeyEnv": "sk-test",
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
    assert body[0]["apiKey"] == ""
    assert body[0]["apiKeyEnv"] == ""
    assert "sk-test" not in models_file.read_text(encoding="utf-8")

    listed = client.get("/api/workspace/models")
    assert listed.status_code == 200
    assert listed.json() == body


def test_workspace_model_config_can_store_direct_api_key(tmp_path, monkeypatch):
    models_file = tmp_path / "models.json"
    monkeypatch.setattr(workspace_api, "WORKSPACE_MODELS_FILE", models_file)
    client = TestClient(app)

    payload = [
        {
            "id": "model_direct",
            "name": "直写 Key 测试",
            "provider": "custom",
            "model": "model-a",
            "baseUrl": "https://api.example.com/v1",
            "apiKey": "direct-token",
            "apiKeyEnv": "SHOULD_NOT_PERSIST",
            "apiKeyMode": "direct",
            "apiVersion": "",
            "organization": "",
            "homepage": "",
            "apiFormat": "openai_compatible",
            "extraOptionsJson": "{}",
            "modelRowsJson": "[]",
            "modelsJson": "{}",
            "enabled": True,
            "isDefault": True,
            "notes": "",
        }
    ]

    saved = client.put("/api/workspace/models", json=payload)

    assert saved.status_code == 200
    body = saved.json()
    assert body[0]["apiKeyMode"] == "direct"
    assert body[0]["apiKey"] == "direct-token"
    assert body[0]["apiKeyEnv"] == ""
    assert "direct-token" in models_file.read_text(encoding="utf-8")


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


def test_workspace_skills_are_persisted_and_imported_from_local_markdown(tmp_path, monkeypatch):
    skills_file = tmp_path / "skills.json"
    config_skills_dir = tmp_path / "config" / "skills"
    monkeypatch.setattr(workspace_api, "WORKSPACE_SKILLS_FILE", skills_file)
    monkeypatch.setattr(workspace_api, "CONFIG_SKILLS_DIR", config_skills_dir)
    source = tmp_path / "source_skills"
    writer_dir = source / "writer"
    writer_dir.mkdir(parents=True)
    (writer_dir / "SKILL.md").write_text(
        """---
name: Writer Skill
description: 写作风格控制
---
# Writer Skill

请使用清晰、克制的中文输出。
""",
        encoding="utf-8",
    )
    (writer_dir / "notes.md").write_text("# Notes\n\n关联说明。", encoding="utf-8")
    (source / "standalone.md").write_text("# Standalone Skill\n\n普通 Markdown skill。", encoding="utf-8")
    ignored_dir = source / "node_modules"
    ignored_dir.mkdir()
    (ignored_dir / "ignored.md").write_text("# Ignored", encoding="utf-8")
    client = TestClient(app)

    response = client.post(
        "/api/workspace/skills/import",
        json={"sourceType": "local", "source": str(source), "useMirror": True},
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["imported"]) == 2
    assert Path(body["importPath"]).is_dir()
    assert Path(body["importPath"]).is_relative_to(config_skills_dir)
    names = {item["name"] for item in body["imported"]}
    assert names == {"Writer Skill", "Standalone Skill"}
    writer = next(item for item in body["imported"] if item["name"] == "Writer Skill")
    assert "请使用清晰" in writer["content"]
    assert "notes.md" in writer["metadataJson"]
    assert "ignored.md" not in "\n".join(body["detectedFiles"])
    assert client.get("/api/workspace/skills").json() == body["allConfigs"]

    saved = client.put(
        "/api/workspace/skills",
        json=[
            {
                "id": "skill_manual",
                "name": "手动 Skill",
                "description": "手动配置",
                "sourceType": "manual",
                "sourcePath": "",
                "filePath": "",
                "content": "手动内容",
                "metadataJson": "",
                "enabled": True,
            }
        ],
    )
    assert saved.status_code == 200
    assert saved.json()[0]["metadataJson"] == "{}"


def test_workspace_skills_upload_detects_multiple_skills(tmp_path, monkeypatch):
    skills_file = tmp_path / "skills.json"
    config_skills_dir = tmp_path / "config" / "skills"
    monkeypatch.setattr(workspace_api, "WORKSPACE_SKILLS_FILE", skills_file)
    monkeypatch.setattr(workspace_api, "CONFIG_SKILLS_DIR", config_skills_dir)
    client = TestClient(app)

    response = client.post(
        "/api/workspace/skills/upload",
        data={"rootName": "upload-skills"},
        files=[
            ("files", ("pack/SKILL.md", b"# Uploaded Skill\n\nUse uploaded rules.", "text/markdown")),
            ("files", ("pack/extra.md", b"# Extra\n\nRelated file.", "text/markdown")),
            ("files", ("loose.md", b"# Loose Skill\n\nStandalone upload.", "text/markdown")),
            ("files", ("pack/.git/ignored.md", b"# Ignored", "text/markdown")),
        ],
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["imported"]) == 2
    assert {item["name"] for item in body["imported"]} == {"Uploaded Skill", "Loose Skill"}
    assert "extra.md" in "\n".join(body["detectedFiles"])
    assert "ignored.md" not in "\n".join(body["detectedFiles"])


def test_workspace_mcp_imports_local_codex_config(tmp_path, monkeypatch):
    mcp_file = tmp_path / "mcp_servers.json"
    config_mcp_dir = tmp_path / "config" / "mcp"
    monkeypatch.setattr(workspace_api, "WORKSPACE_MCP_FILE", mcp_file)
    monkeypatch.setattr(workspace_api, "CONFIG_MCP_DIR", config_mcp_dir)
    source = tmp_path / "source_mcp"
    codex_dir = source / ".codex"
    codex_dir.mkdir(parents=True)
    (codex_dir / "config.toml").write_text(
        """
[mcp_servers.context7]
command = "npx"
args = ["-y", "@upstash/context7-mcp"]
env_vars = ["LOCAL_TOKEN"]
cwd = "."
startup_timeout_sec = 20

[mcp_servers.figma]
url = "https://mcp.figma.com/mcp"
bearer_token_env_var = "FIGMA_OAUTH_TOKEN"
http_headers = { "X-Figma-Region" = "us-east-1" }
env_http_headers = { "X-Feature-Flag" = "FIGMA_FEATURE_FLAG" }
enabled = true
""",
        encoding="utf-8",
    )
    client = TestClient(app)

    response = client.post(
        "/api/workspace/mcp/import",
        json={"sourceType": "local", "source": str(source), "useMirror": True},
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["imported"]) == 2
    assert Path(body["importPath"]).is_dir()
    assert Path(body["importPath"]).is_relative_to(config_mcp_dir)
    stdio = next(item for item in body["imported"] if item["transport"] == "stdio")
    assert stdio["command"] == "npx"
    assert '"@upstash/context7-mcp"' in stdio["argsJson"]
    assert '"LOCAL_TOKEN"' in stdio["envVarsJson"]
    remote = next(item for item in body["imported"] if item["transport"] == "http")
    assert remote["url"] == "https://mcp.figma.com/mcp"
    assert remote["bearerTokenEnvVar"] == "FIGMA_OAUTH_TOKEN"
    assert "X-Figma-Region" in remote["httpHeadersJson"]
    assert client.get("/api/workspace/mcp").json() == body["allConfigs"]


def test_workspace_tools_imports_local_python_functions(tmp_path, monkeypatch):
    tools_file = tmp_path / "tools.json"
    config_tools_dir = tmp_path / "config" / "tools"
    monkeypatch.setattr(workspace_api, "WORKSPACE_TOOLS_FILE", tools_file)
    monkeypatch.setattr(workspace_api, "CONFIG_TOOLS_DIR", config_tools_dir)
    source = tmp_path / "source_tools"
    source.mkdir()
    (source / "tools.py").write_text(
        '''
from langchain_core.tools import tool


@tool("search_docs")
def search_documents(query: str, limit: int = 3) -> str:
    """Search local documents."""
    return query


def helper(value: str) -> str:
    """Not imported when decorated tools exist."""
    return value
''',
        encoding="utf-8",
    )
    client = TestClient(app)

    response = client.post(
        "/api/workspace/tools/import",
        json={"sourceType": "local", "source": str(source), "useMirror": True},
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["imported"]) == 1
    imported = body["imported"][0]
    assert imported["name"] == "search_docs"
    assert imported["source"] == "python"
    assert imported["description"] == "Search local documents."
    schema = json.loads(imported["schemaJson"])
    assert schema["properties"]["query"]["type"] == "string"
    assert schema["properties"]["limit"]["type"] == "number"
    assert schema["required"] == ["query"]
    assert schema["x-graphic"]["function"] == "search_documents"
    assert Path(body["importPath"]).is_relative_to(config_tools_dir)
    assert client.get("/api/workspace/tools").json() == body["allConfigs"]


def test_workspace_tools_upload_detects_openapi_operations(tmp_path, monkeypatch):
    tools_file = tmp_path / "tools.json"
    config_tools_dir = tmp_path / "config" / "tools"
    monkeypatch.setattr(workspace_api, "WORKSPACE_TOOLS_FILE", tools_file)
    monkeypatch.setattr(workspace_api, "CONFIG_TOOLS_DIR", config_tools_dir)
    client = TestClient(app)
    openapi = {
        "openapi": "3.0.0",
        "paths": {
            "/orders/{order_id}": {
                "get": {
                    "operationId": "get_order",
                    "summary": "查询订单",
                    "parameters": [
                        {
                            "name": "order_id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                }
            }
        },
    }

    response = client.post(
        "/api/workspace/tools/upload",
        data={"rootName": "openapi-tools"},
        files=[("files", ("openapi-tools/openapi.json", json.dumps(openapi).encode("utf-8"), "application/json"))],
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["imported"]) == 1
    imported = body["imported"][0]
    assert imported["name"] == "get_order"
    assert imported["source"] == "openapi"
    schema = json.loads(imported["schemaJson"])
    assert schema["properties"]["order_id"]["type"] == "string"
    assert schema["x-graphic"]["method"] == "GET"
    assert schema["x-graphic"]["path"] == "/orders/{order_id}"
    assert Path(body["importPath"]).is_relative_to(config_tools_dir)
    assert (Path(body["importPath"]) / "openapi.json").is_file()
    assert "openapi.json" in "\n".join(body["detectedFiles"])


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


def test_workspace_rag_inspect_detects_chroma_sidecar(tmp_path):
    data_dir = tmp_path / "rag_data"
    chroma_dir = data_dir / "chroma"
    chroma_dir.mkdir(parents=True)
    (chroma_dir / "chroma.sqlite3").write_bytes(b"")
    (data_dir / "runtime_config.json").write_text(
        """
        {
          "COLLECTION_NAME": "national_formulary_v2",
          "EMBEDDING_MODEL": "text-embedding-v4",
          "EMBEDDING_API_BASE": "https://dashscope.aliyuncs.com/compatible-mode/v1",
          "EMBEDDING_API_KEY": "sk-do-not-copy",
          "TOP_K": 8
        }
        """,
        encoding="utf-8",
    )
    client = TestClient(app)

    response = client.post("/api/workspace/rag/inspect", json={"path": str(data_dir)})

    assert response.status_code == 200
    body = response.json()
    assert body["exists"] is True
    assert body["sourceType"] == "vectorstore"
    assert body["path"] == str(chroma_dir)
    assert body["collection"] == "national_formulary_v2"
    assert body["embeddingModel"] == "text-embedding-v4"
    assert body["topK"] == 8
    assert "chroma.sqlite3" in "\n".join(body["detectedFiles"])
    assert "runtime_config.json" in "\n".join(body["detectedFiles"])
    assert "sk-do-not-copy" not in body["metadataJson"]
    assert '"embeddingApiKeyEnv": "EMBEDDING_API_KEY"' in body["metadataJson"]
