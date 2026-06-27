import json
from pathlib import Path

from fastapi.testclient import TestClient

import app.config as app_config
import app.api.workspace as workspace_api
import app.run_store as run_store
import app.runtime_environment as runtime_environment
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


def test_project_run_preview_preserves_data_shaping_trace_metadata():
    client = TestClient(app)

    created = client.post("/api/projects", json={"name": "Trace 元数据测试 Agent"})
    assert created.status_code == 200
    project = created.json()
    project_id = project["project"]["id"]
    project["nodes"].append(
        {
            "id": "assign_1",
            "type": "variable_assign",
            "label": "Variable Assign",
            "position": {"x": 320, "y": 220},
            "config": {
                "assignmentsJson": json.dumps(
                    [{"target": "assigned_value", "operation": "overwrite", "sourceType": "state", "source": "messages", "valueType": "string"}]
                ),
                "resultField": "assignment_result",
            },
            "inputs": [{"id": "in", "type": "control", "label": "输入"}],
            "outputs": [{"id": "out", "type": "control", "label": "输出"}],
        }
    )
    project["edges"].append({"id": "e1", "source": "start", "sourceHandle": "out", "target": "assign_1", "kind": "normal"})
    assert client.put(f"/api/projects/{project_id}", json=project).status_code == 200

    preview = client.post(f"/api/projects/{project_id}/run", json={"input": {"messages": "hello"}})
    assert preview.status_code == 200
    trace_item = preview.json()["trace"][0]
    assert trace_item["dataShaping"]["kind"] == "variable_assign"
    assert trace_item["dataShaping"]["changedFields"] == ["assigned_value"]

    assert client.delete(f"/api/projects/{project_id}").status_code == 204


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


def test_project_run_human_approval_pauses_and_resumes(tmp_path, monkeypatch):
    runs_dir = tmp_path / "runs"
    monkeypatch.setattr(app_config, "RUNS_DIR", runs_dir)
    monkeypatch.setattr(run_store, "RUNS_DIR", runs_dir)
    client = TestClient(app)

    created = client.post("/api/projects", json={"name": "人工审批恢复 Agent"})
    assert created.status_code == 200
    project = created.json()
    project_id = project["project"]["id"]
    project["state"]["fields"].extend(
        [
            {"name": "approval_action", "type": "str", "description": ""},
            {"name": "approval_result", "type": "dict", "description": ""},
            {"name": "final_answer", "type": "str", "description": ""},
        ]
    )
    project["nodes"].extend(
        [
            {
                "id": "approval_1",
                "type": "human_approval",
                "label": "人工审批",
                "position": {"x": 320, "y": 220},
                "config": {
                    "prompt": "请确认是否继续：{{ state.messages }}",
                    "actions": "approved,rejected,edit",
                    "actionField": "approval_action",
                    "outputField": "approval_result",
                    "fallback": "rejected",
                },
                "inputs": [{"id": "in", "type": "control", "label": "输入"}],
                "outputs": [
                    {"id": "approved", "type": "control", "label": "通过"},
                    {"id": "rejected", "type": "control", "label": "拒绝"},
                    {"id": "edit", "type": "control", "label": "修改"},
                ],
            },
            {
                "id": "reply_ok",
                "type": "direct_reply",
                "label": "通过回复",
                "position": {"x": 560, "y": 180},
                "config": {"template": "approved: {{ state.approval_result.comment }}", "outputField": "final_answer"},
                "inputs": [{"id": "in", "type": "control", "label": "输入"}],
                "outputs": [],
            },
            {
                "id": "reply_no",
                "type": "direct_reply",
                "label": "拒绝回复",
                "position": {"x": 560, "y": 260},
                "config": {"template": "rejected: {{ state.approval_result.comment }}", "outputField": "final_answer"},
                "inputs": [{"id": "in", "type": "control", "label": "输入"}],
                "outputs": [],
            },
            {
                "id": "reply_edit",
                "type": "direct_reply",
                "label": "修改回复",
                "position": {"x": 560, "y": 340},
                "config": {"template": "edit: {{ state.approval_result.comment }}", "outputField": "final_answer"},
                "inputs": [{"id": "in", "type": "control", "label": "输入"}],
                "outputs": [],
            },
        ]
    )
    project["edges"].extend(
        [
            {"id": "e_start_approval", "source": "start", "sourceHandle": "out", "target": "approval_1", "kind": "normal"},
            {"id": "e_approved", "source": "approval_1", "sourceHandle": "approved", "target": "reply_ok", "kind": "conditional"},
            {"id": "e_rejected", "source": "approval_1", "sourceHandle": "rejected", "target": "reply_no", "kind": "conditional"},
            {"id": "e_edit", "source": "approval_1", "sourceHandle": "edit", "target": "reply_edit", "kind": "conditional"},
        ]
    )
    assert client.put(f"/api/projects/{project_id}", json=project).status_code == 200

    preview = client.post(f"/api/projects/{project_id}/run", json={"input": {"messages": "退款申请"}, "mode": "live"})
    assert preview.status_code == 200
    paused = preview.json()
    assert paused["status"] == "paused"
    assert paused["pendingApproval"]["nodeId"] == "approval_1"
    assert paused["pendingApproval"]["actions"] == ["approved", "rejected", "edit"]
    assert paused["trace"][-1]["pause"] is True

    record = {
        "id": "history_pending_approval",
        "projectId": project_id,
        "projectName": "人工审批恢复 Agent",
        "createdAt": "2026-06-27T00:00:00.000Z",
        "modelConfigId": None,
        "modelConfigName": "未选择模型",
        "inputState": {"messages": "退款申请"},
        "result": paused,
        "runtimeNodes": {},
    }
    assert client.post(f"/api/projects/{project_id}/runs", json=record).status_code == 200

    resumed = client.post(
        f"/api/projects/{project_id}/runs/history_pending_approval/resume",
        json={"action": "edit", "comment": "需要补充材料"},
    )
    assert resumed.status_code == 200
    body = resumed.json()
    assert body["status"] == "completed"
    assert body["pendingApproval"] is None
    assert body["outputState"]["approval_action"] == "edit"
    assert body["outputState"]["approval_result"]["status"] == "resumed"
    assert body["outputState"]["approval_result"]["comment"] == "需要补充材料"
    assert body["outputState"]["final_answer"] == "edit: 需要补充材料"
    assert body["trace"][-2]["approval"]["availableActions"] == ["approved", "rejected", "edit"]

    run_file = runs_dir / project_id / "history_pending_approval.json"
    saved = json.loads(run_file.read_text(encoding="utf-8"))
    assert saved["result"]["status"] == "completed"
    assert saved["result"]["outputState"]["final_answer"] == "edit: 需要补充材料"

    repeated = client.post(
        f"/api/projects/{project_id}/runs/history_pending_approval/resume",
        json={"action": "rejected", "comment": "重复提交"},
    )
    assert repeated.status_code == 409
    assert "not paused" in repeated.json()["detail"]


def test_project_run_history_persists_to_runs_dir(tmp_path, monkeypatch):
    runs_dir = tmp_path / "runs"
    monkeypatch.setattr(app_config, "RUNS_DIR", runs_dir)
    monkeypatch.setattr(run_store, "RUNS_DIR", runs_dir)
    client = TestClient(app)

    created = client.post("/api/projects", json={"name": "运行历史落盘 Agent"})
    assert created.status_code == 200
    project_id = created.json()["project"]["id"]
    record = {
        "id": "history_test_run",
        "projectId": project_id,
        "projectName": "运行历史落盘 Agent",
        "createdAt": "2026-06-26T00:00:00.000Z",
        "modelConfigId": None,
        "modelConfigName": "测试模型",
        "inputState": {"messages": "hello"},
        "result": {"mode": "live", "valid": True, "issues": [], "trace": [], "outputState": {"answer": "ok"}},
        "runtimeNodes": {},
    }

    saved = client.post(f"/api/projects/{project_id}/runs", json=record)
    assert saved.status_code == 200
    run_file = runs_dir / project_id / "history_test_run.json"
    assert run_file.exists()
    assert json.loads(run_file.read_text(encoding="utf-8"))["result"]["outputState"]["answer"] == "ok"

    listed = client.get(f"/api/projects/{project_id}/runs")
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == "history_test_run"

    deleted = client.delete(f"/api/projects/{project_id}/runs/history_test_run")
    assert deleted.status_code == 204
    assert not run_file.exists()

    saved_again = client.post(f"/api/projects/{project_id}/runs", json=record)
    assert saved_again.status_code == 200
    cleared = client.delete(f"/api/projects/{project_id}/runs")
    assert cleared.status_code == 204
    assert not (runs_dir / project_id).exists()

    assert client.delete(f"/api/projects/{project_id}").status_code == 204


def test_data_shaping_paths_and_preview_use_run_history(tmp_path, monkeypatch):
    runs_dir = tmp_path / "runs"
    monkeypatch.setattr(app_config, "RUNS_DIR", runs_dir)
    monkeypatch.setattr(run_store, "RUNS_DIR", runs_dir)
    client = TestClient(app)

    created = client.post("/api/projects", json={"name": "数据塑形预览 Agent"})
    assert created.status_code == 200
    project = created.json()
    project_id = project["project"]["id"]
    project["state"]["fields"].append({"name": "template_result", "type": "dict", "description": ""})
    project["nodes"].append(
        {
            "id": "template_1",
            "type": "template",
            "label": "Template",
            "position": {"x": 320, "y": 220},
            "config": {
                "inputMappingsJson": '[{"name":"titles","sourceType":"state","source":"task_plan.tasks[].title","transform":"join","transformArgsJson":"{\\"separator\\":\\",\\"}","valueType":"string"}]',
                "template": "{\"titles\":\"{{ state.titles }}\"}",
                "outputType": "json",
                "outputField": "template_result",
            },
            "inputs": [{"id": "in", "type": "control", "label": "输入"}],
            "outputs": [{"id": "out", "type": "control", "label": "输出"}],
        }
    )
    assert client.put(f"/api/projects/{project_id}", json=project).status_code == 200

    record = {
        "id": "history_data_shape",
        "projectId": project_id,
        "projectName": "数据塑形预览 Agent",
        "createdAt": "2026-06-26T00:00:00.000Z",
        "modelConfigId": None,
        "modelConfigName": "测试模型",
        "inputState": {"messages": "hello"},
        "result": {
            "mode": "live",
            "valid": True,
            "issues": [],
            "trace": [{"nodeId": "x", "type": "template", "label": "X", "status": "ok", "detail": "", "durationMs": 0, "inputState": {}, "outputDelta": {"task_plan": {"tasks": [{"title": "A"}, {"title": "B"}]}}}],
            "outputState": {"task_plan": {"tasks": [{"title": "A"}, {"title": "B"}]}},
        },
        "runtimeNodes": {},
    }
    assert client.post(f"/api/projects/{project_id}/runs", json=record).status_code == 200

    paths = client.post(f"/api/projects/{project_id}/data-shaping/paths", json={"runId": "history_data_shape"})
    assert paths.status_code == 200
    assert any(item["path"] == "task_plan.tasks[].title" for item in paths.json()["paths"])

    preview = client.post(f"/api/projects/{project_id}/data-shaping/preview", json={"nodeId": "template_1", "runId": "history_data_shape"})
    assert preview.status_code == 200
    body = preview.json()
    assert body["ok"] is True
    assert body["inputs"]["titles"] == "A,B"
    assert body["delta"]["template_result"] == {"titles": "A,B"}

    assert client.delete(f"/api/projects/{project_id}").status_code == 204


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


def test_project_save_and_read_preserves_template_metadata():
    client = TestClient(app)

    created = client.post("/api/projects", json={"name": "模板来源保存测试 Agent"})
    assert created.status_code == 200
    project = created.json()
    project_id = project["project"]["id"]
    project["project"]["templateId"] = "api_json_cleanup"
    project["project"]["templateVersion"] = "1.0.0"

    saved = client.put(f"/api/projects/{project_id}", json=project)
    assert saved.status_code == 200
    assert saved.json()["project"]["templateId"] == "api_json_cleanup"
    assert saved.json()["project"]["templateVersion"] == "1.0.0"

    loaded = client.get(f"/api/projects/{project_id}")
    assert loaded.status_code == 200
    assert loaded.json()["project"]["templateId"] == "api_json_cleanup"
    assert loaded.json()["project"]["templateVersion"] == "1.0.0"

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


def test_workspace_runtime_environments_are_persisted(tmp_path, monkeypatch):
    runtime_file = tmp_path / "runtime_environments.json"
    monkeypatch.setattr(runtime_environment, "WORKSPACE_RUNTIME_ENVIRONMENTS_FILE", runtime_file)
    client = TestClient(app)

    default_response = client.get("/api/workspace/runtime-environments")
    assert default_response.status_code == 200
    assert default_response.json()[0]["kind"] == "local_backend"

    payload = [
        {
            "id": "runtime_docs",
            "name": "本地文档环境",
            "kind": "local_backend",
            "description": "只允许 docs",
            "allowedRootsJson": json.dumps([str(tmp_path / "docs")]),
            "networkEnabled": False,
            "allowAllHosts": True,
            "allowedHostsJson": "[]",
            "maxFileBytes": 4096,
            "maxHttpBytes": 8192,
        }
    ]
    saved = client.put("/api/workspace/runtime-environments", json=payload)

    assert saved.status_code == 200
    assert runtime_file.exists()
    assert saved.json()[0]["name"] == "本地文档环境"
    assert saved.json()[0]["networkEnabled"] is False
    assert saved.json()[0]["allowAllHosts"] is True
    assert saved.json()[0]["allowedHostsJson"] == "[]"
    assert client.get("/api/workspace/runtime-environments").json() == saved.json()


def test_builtin_tool_presets_can_be_installed(tmp_path, monkeypatch):
    tools_file = tmp_path / "tools.json"
    monkeypatch.setattr(workspace_api, "WORKSPACE_TOOLS_FILE", tools_file)
    client = TestClient(app)

    presets = client.get("/api/workspace/tools/presets")
    assert presets.status_code == 200
    preset_ids = {item["id"] for item in presets.json()}
    assert {
        "builtin_web_search",
        "builtin_task_plan",
        "builtin_read_file",
        "builtin_list_directory",
        "builtin_read_file_chunk",
        "builtin_search_code",
        "builtin_list_code_symbols",
        "builtin_extract_html",
        "builtin_extract_css_rules",
        "builtin_extract_html_by_text",
        "builtin_extract_css_for_html",
        "builtin_summarize_page_structure",
        "builtin_resolve_asset_references",
        "builtin_extract_code_symbol",
        "builtin_chunk_code_semantic",
        "builtin_fetch_url",
    }.issubset(preset_ids)

    installed = client.post("/api/workspace/tools/presets/install", json={"ids": ["builtin_read_file"]})
    assert installed.status_code == 200
    body = installed.json()
    assert body["imported"][0]["source"] == "builtin"
    assert body["imported"][0]["name"] == "read_file"
    schema = json.loads(body["imported"][0]["schemaJson"])
    assert schema["x-graphic"]["builtinId"] == "read_file"
    assert client.get("/api/workspace/tools").json() == body["allConfigs"]


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
    (writer_dir / "metadata.json").write_text('{"version": "1.0.0", "category": "Writing"}', encoding="utf-8")
    scripts_dir = writer_dir / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "format.sh").write_text("#!/usr/bin/env bash\necho format\n", encoding="utf-8")
    assets_dir = writer_dir / "assets"
    assets_dir.mkdir()
    (assets_dir / "template.txt").write_text("模板内容", encoding="utf-8")
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
    metadata = json.loads(writer["metadataJson"])
    assert metadata["packageMetadata"]["version"] == "1.0.0"
    assert metadata["frontmatter"]["description"] == "写作风格控制"
    assert metadata["relatedMarkdown"][0]["path"].endswith("notes.md")
    assert "关联说明" in metadata["relatedMarkdown"][0]["content"]
    assert any(item["path"].endswith("scripts/format.sh") and item["kind"] == "script" for item in metadata["supportFiles"])
    assert any(item["path"].endswith("assets/template.txt") for item in metadata["supportFiles"])
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


def test_workspace_mcp_inspect_returns_tools(monkeypatch):
    def fake_inspect(config, runtime_environment=None):
        assert config["url"] == "https://mcp.exa.ai/mcp"
        return {
            "ok": True,
            "serverId": config["id"],
            "serverName": config["name"],
            "transport": config["transport"],
            "tools": [
                {
                    "name": "web_search_exa",
                    "title": "Web Search",
                    "description": "Search web",
                    "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}},
                }
            ],
            "warnings": [],
            "durationMs": 3.5,
        }

    monkeypatch.setattr(workspace_api, "inspect_mcp_server", fake_inspect)
    client = TestClient(app)

    response = client.post(
        "/api/workspace/mcp/inspect",
        json={
            "id": "mcp_exa",
            "name": "Exa MCP",
            "transport": "http",
            "url": "https://mcp.exa.ai/mcp",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["tools"][0]["name"] == "web_search_exa"
    assert body["tools"][0]["inputSchema"]["properties"]["query"]["type"] == "string"


def test_workspace_mcp_saves_api_key_modes(tmp_path, monkeypatch):
    mcp_file = tmp_path / "mcp_servers.json"
    monkeypatch.setattr(workspace_api, "WORKSPACE_MCP_FILE", mcp_file)
    client = TestClient(app)

    response = client.put(
        "/api/workspace/mcp",
        json=[
            {
                "id": "exa_env",
                "name": "Exa Env",
                "transport": "http",
                "url": "https://mcp.exa.ai/mcp",
                "apiKeyMode": "env",
                "apiKeyEnv": "EXA_API_KEY",
                "apiKey": "should-drop",
                "apiKeyHeader": "x-api-key",
                "apiKeyPrefix": "",
            },
            {
                "id": "exa_direct",
                "name": "Exa Direct",
                "transport": "http",
                "url": "https://mcp.exa.ai/mcp",
                "apiKeyMode": "direct",
                "apiKey": "direct-token",
                "apiKeyEnv": "SHOULD_DROP",
                "apiKeyHeader": "x-api-key",
                "apiKeyPrefix": "",
            },
        ],
    )

    assert response.status_code == 200
    body = response.json()
    env_config = next(item for item in body if item["id"] == "exa_env")
    direct_config = next(item for item in body if item["id"] == "exa_direct")
    assert env_config["apiKeyMode"] == "env"
    assert env_config["apiKeyEnv"] == "EXA_API_KEY"
    assert env_config["apiKey"] == ""
    assert direct_config["apiKeyMode"] == "direct"
    assert direct_config["apiKey"] == "direct-token"
    assert direct_config["apiKeyEnv"] == ""


def test_workspace_mcp_inspect_returns_structured_failure(monkeypatch):
    def fake_inspect(config, runtime_environment=None):
        raise RuntimeError("connect failed")

    monkeypatch.setattr(workspace_api, "inspect_mcp_server", fake_inspect)
    client = TestClient(app)

    response = client.post(
        "/api/workspace/mcp/inspect",
        json={
            "id": "mcp_bad",
            "name": "Bad MCP",
            "transport": "http",
            "url": "https://mcp.example.invalid/mcp",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["serverId"] == "mcp_bad"
    assert "connect failed" in body["error"]


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
