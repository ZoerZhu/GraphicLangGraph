import json
import os
import subprocess
import sys
import zipfile

from app.compiler import build_project, export_project_zip, generate_project_files
from app.compiler.codegen import package_name
from app.ir.schemas import EdgeIR, EdgeKind, ImportedAgentConfig, MCPServerConfig, NodeIR, NodeType, Position, StateField, ToolConfig, create_default_project


def sample_project():
    project = create_default_project("客服 Agent")
    project.state.fields.append(StateField(name="final_answer", type="str"))
    project.nodes.extend(
        [
            NodeIR(
                id="llm_1",
                type=NodeType.LLM,
                label="生成回答",
                position=Position(x=320, y=220),
                config={"outputField": "final_answer"},
            ),
            NodeIR(
                id="reply_1",
                type=NodeType.DIRECT_REPLY,
                label="回复",
                position=Position(x=560, y=220),
                config={"template": "{{ state.final_answer }}"},
            ),
        ]
    )
    project.edges.extend(
        [
            EdgeIR(id="e1", source="start", target="llm_1"),
            EdgeIR(id="e2", source="llm_1", target="reply_1"),
        ]
    )
    return project


def test_codegen_contains_required_files():
    files = generate_project_files(sample_project())

    assert "langgraph.json" in files
    assert "pyproject.toml" in files
    assert "tests/test_graph_smoke.py" in files
    assert any(path.endswith("/graph.py") for path in files)
    assert any(path.endswith("/state.py") for path in files)


def test_export_zip_contains_required_files():
    export_id, zip_path, files, smoke_test = export_project_zip(sample_project())

    assert export_id
    assert zip_path.exists()
    assert smoke_test.passed
    assert "langgraph.json" in files
    with zipfile.ZipFile(zip_path) as archive:
        names = set(archive.namelist())

    assert "langgraph.json" in names
    assert "README.md" in names
    assert "flow/project.graph.json" in names


def test_codegen_exports_mcp_runtime_and_node_call():
    project = create_default_project("MCP Export Agent")
    project.mcpServers.append(
        MCPServerConfig(
            id="exa",
            name="Exa MCP",
            transport="http",
            url="https://mcp.exa.ai/mcp",
            envHttpHeadersJson='{"x-api-key":"EXA_API_KEY"}',
            enabledToolsJson='["web_search_exa"]',
        )
    )
    project.state.fields.extend([StateField(name="messages", type="str"), StateField(name="mcp_result", type="dict")])
    project.nodes.extend(
        [
            NodeIR(
                id="mcp_1",
                type=NodeType.MCP_NODE,
                label="Exa Search",
                config={
                    "serverId": "exa",
                    "serverName": "Exa MCP",
                    "toolName": "web_search_exa",
                    "toolArgsJson": '{"query":"{{ state.messages }}"}',
                    "outputField": "mcp_result",
                },
            ),
            NodeIR(id="reply_1", type=NodeType.DIRECT_REPLY, label="回复", config={"template": "{{ state.mcp_result }}"}),
        ]
    )
    project.edges.extend([EdgeIR(id="e1", source="start", target="mcp_1"), EdgeIR(id="e2", source="mcp_1", target="reply_1")])

    files = generate_project_files(project)
    nodes_py = next(value for path, value in files.items() if path.endswith("/nodes.py"))
    mcp_runtime_py = next(value for path, value in files.items() if path.endswith("/mcp_runtime.py"))
    mcp_servers_py = next(value for path, value in files.items() if path.endswith("/mcp_servers.py"))

    assert "mcp>=1.12.4" in files["pyproject.toml"]
    assert "GLG_MCP_ALLOWED_HOSTS=mcp.exa.ai" in files[".env.example"]
    assert "EXA_API_KEY=replace_me" in files[".env.example"]
    assert "MCP_SERVER_REGISTRY" in mcp_servers_py
    assert "https://mcp.exa.ai/mcp" in mcp_servers_py
    assert "def invoke_mcp_tool" in mcp_runtime_py
    assert "def render_json_object" in mcp_runtime_py
    assert "result = invoke_mcp_tool(server, tool_name, args)" in nodes_py
    assert "render_json_object" in nodes_py
    compile(mcp_runtime_py, "mcp_runtime.py", "exec")
    compile(mcp_servers_py, "mcp_servers.py", "exec")
    compile(nodes_py, "nodes.py", "exec")


def test_codegen_exports_agent_mcp_tool_loop():
    project = create_default_project("MCP Agent Export")
    server = MCPServerConfig(id="context7", name="Context7", transport="http", url="https://mcp.context7.com/mcp")
    project.mcpServers.append(server)
    project.state.fields.append(StateField(name="answer", type="str"))
    project.nodes.extend(
        [
            NodeIR(
                id="agent_1",
                type=NodeType.AGENT,
                label="Agent",
                config={
                    "outputField": "answer",
                    "mcpServerIdsJson": '["context7"]',
                    "mcpServerRegistryJson": json.dumps([server.model_dump(by_alias=True)]),
                    "maxIterations": 3,
                },
            ),
            NodeIR(id="reply_1", type=NodeType.DIRECT_REPLY, label="回复", config={"template": "{{ state.answer }}"}),
        ]
    )
    project.edges.extend([EdgeIR(id="e1", source="start", target="agent_1"), EdgeIR(id="e2", source="agent_1", target="reply_1")])

    files = generate_project_files(project)
    nodes_py = next(value for path, value in files.items() if path.endswith("/nodes.py"))
    mcp_runtime_py = next(value for path, value in files.items() if path.endswith("/mcp_runtime.py"))

    assert "list_mcp_tools(server)" in nodes_py
    assert "make_mcp_agent_tool_config(server, mcp_tool)" in nodes_py
    assert "run_mcp_agent_session" in nodes_py
    assert '"answer_mcp_tool_calls"' in nodes_py
    assert "_run_export_tool_agent_session" in nodes_py
    assert "serverName" in mcp_runtime_py
    assert "toolName" in mcp_runtime_py
    assert "durationMs" in mcp_runtime_py
    compile(nodes_py, "nodes.py", "exec")


def test_codegen_exports_mcp_node_model_tool_selection():
    project = create_default_project("MCP Model Export")
    project.mcpServers.append(MCPServerConfig(id="exa", name="Exa MCP", transport="http", url="https://mcp.exa.ai/mcp"))
    project.nodes.append(
        NodeIR(
            id="mcp_1",
            type=NodeType.MCP_NODE,
            label="Exa",
            config={
                "serverId": "exa",
                "serverName": "Exa MCP",
                "toolSelectionMode": "model",
                "toolSelectionInstruction": "搜索问题优先 web_search_exa",
                "toolSelectionModelProvider": "openai",
                "toolSelectionModel": "gpt-4.1-mini",
                "toolSelectionApiKeyEnv": "OPENAI_API_KEY",
                "fallbackToHeuristic": False,
                "outputField": "mcp_result",
            },
        )
    )
    project.edges.append(EdgeIR(id="e1", source="start", target="mcp_1"))

    files = generate_project_files(project)
    nodes_py = next(value for path, value in files.items() if path.endswith("/nodes.py"))

    assert "_run_mcp_node_auto_call" in nodes_py
    assert "_select_mcp_tool_with_model" in nodes_py
    assert "web_search_exa" in nodes_py


def test_codegen_exports_workflow_core_data_shaping_nodes():
    project = create_default_project("Workflow Core Export")
    project.state.fields.extend(
        [
            StateField(name="assigned_value", type="str"),
            StateField(name="assignment_result", type="dict"),
            StateField(name="template_result", type="dict"),
            StateField(name="validated_json", type="dict"),
            StateField(name="validation_result", type="dict"),
            StateField(name="final_answer", type="str"),
        ]
    )
    schema_fields = json.dumps([{"name": "message", "type": "string", "required": True, "description": "消息"}])
    project.nodes.extend(
        [
            NodeIR(
                id="assign_1",
                type=NodeType.VARIABLE_ASSIGN,
                label="Assign",
                config={
                    "assignmentsJson": json.dumps([{"target": "assigned_value", "operation": "overwrite", "sourceType": "state", "source": "messages", "valueType": "string"}]),
                    "resultField": "assignment_result",
                },
            ),
            NodeIR(id="template_1", type=NodeType.TEMPLATE, label="Template", config={"template": '{"message":"{{ state.assigned_value }}"}', "outputType": "json", "outputField": "template_result"}),
            NodeIR(
                id="validator_1",
                type=NodeType.JSON_VALIDATOR,
                label="Validator",
                config={"inputField": "template_result", "schemaFieldsJson": schema_fields, "outputField": "validated_json", "validationField": "validation_result"},
                outputs=[
                    {"id": "valid", "type": "condition", "label": "valid"},
                    {"id": "invalid", "type": "condition", "label": "invalid"},
                ],
            ),
            NodeIR(id="reply_valid", type=NodeType.DIRECT_REPLY, label="Valid Reply", config={"template": "{{ state.validated_json }}", "outputField": "final_answer"}),
            NodeIR(id="reply_invalid", type=NodeType.DIRECT_REPLY, label="Invalid Reply", config={"template": "invalid", "outputField": "final_answer"}),
        ]
    )
    project.edges.extend(
        [
            EdgeIR(id="e1", source="start", target="assign_1"),
            EdgeIR(id="e2", source="assign_1", target="template_1"),
            EdgeIR(id="e3", source="template_1", target="validator_1"),
            EdgeIR(id="e4", source="validator_1", target="reply_valid", kind=EdgeKind.CONDITIONAL, sourceHandle="valid"),
            EdgeIR(id="e5", source="validator_1", target="reply_invalid", kind=EdgeKind.CONDITIONAL, sourceHandle="invalid"),
        ]
    )

    export_id, zip_path, files, smoke_test = export_project_zip(project)
    generated = generate_project_files(project)
    nodes_py = next(value for path, value in generated.items() if path.endswith("/nodes.py"))
    routers_py = next(value for path, value in generated.items() if path.endswith("/routers.py"))

    assert export_id
    assert zip_path.exists()
    assert smoke_test.passed
    assert "_run_variable_assign" in nodes_py
    assert "_validation_result" in nodes_py
    assert "def route_validator_1" in routers_py
    assert "valid" in routers_py and "invalid" in routers_py
    compile(nodes_py, "nodes.py", "exec")
    compile(routers_py, "routers.py", "exec")


def test_codegen_exports_json_extractor_model_call():
    project = create_default_project("Extractor Export")
    project.state.fields.extend([StateField(name="extracted_json", type="dict"), StateField(name="validation_result", type="dict")])
    project.nodes.append(
        NodeIR(
            id="extract_1",
            type=NodeType.JSON_EXTRACTOR,
            label="Extractor",
            config={
                "schemaFieldsJson": json.dumps([{"name": "tasks", "type": "array", "required": True}]),
                "outputField": "extracted_json",
                "validationField": "validation_result",
                "instruction": "抽取任务",
            },
        )
    )
    project.edges.append(EdgeIR(id="e1", source="start", target="extract_1"))

    files = generate_project_files(project)
    nodes_py = next(value for path, value in files.items() if path.endswith("/nodes.py"))

    assert "_json_extractor_system_prompt" in nodes_py
    assert "_parse_json_object_from_text" in nodes_py
    assert '"tasks"' in nodes_py
    compile(nodes_py, "nodes.py", "exec")
    assert "OPENAI_API_KEY=replace_me" in files[".env.example"]
    compile(nodes_py, "nodes.py", "exec")


def test_codegen_exports_workflow_core_v2_transform_schema_and_repair():
    project = create_default_project("Workflow Core v2 Export")
    project.nodes.extend(
        [
            NodeIR(
                id="assign_v2",
                type=NodeType.VARIABLE_ASSIGN,
                label="Assign v2",
                config={
                    "assignmentsJson": json.dumps(
                        [
                            {
                                "target": "titles_text",
                                "operation": "overwrite",
                                "sourceType": "state",
                                "source": "task_plan.tasks[].title",
                                "transform": "join",
                                "transformArgsJson": '{"separator": ","}',
                            }
                        ]
                    )
                },
            ),
            NodeIR(
                id="validator_v2",
                type=NodeType.JSON_VALIDATOR,
                label="Validator v2",
                config={
                    "inputField": "task_plan",
                    "schemaPreset": "task_plan_v1",
                    "repairEnabled": True,
                    "repairResultField": "repair_result",
                },
            ),
        ]
    )
    project.edges.extend([EdgeIR(id="e1", source="start", target="assign_v2"), EdgeIR(id="e2", source="assign_v2", target="validator_v2")])

    files = generate_project_files(project)
    nodes_py = next(value for path, value in files.items() if path.endswith("/nodes.py"))

    assert "_apply_mapping_transform" in nodes_py
    assert "_repair_json_output" in nodes_py
    assert "task_plan_v1" in nodes_py
    assert "anyOf" in nodes_py
    assert "tasks[].title" in nodes_py
    compile(nodes_py, "nodes.py", "exec")


def test_codegen_exports_flow_control_nodes():
    project = create_default_project("Flow Control Export")
    project.state.fields.extend(
        [
            StateField(name="items", type="list"),
            StateField(name="merged_results", type="list"),
            StateField(name="merge_result", type="dict"),
            StateField(name="final_answer", type="str"),
        ]
    )
    project.nodes.extend(
        [
            NodeIR(id="each_1", type=NodeType.FOR_EACH, label="ForEach", config={"itemsField": "items", "itemField": "current_item", "indexField": "current_index"}),
            NodeIR(
                id="template_1",
                type=NodeType.TEMPLATE,
                label="Template",
                config={"template": "{{ state.current_item }}", "outputType": "text", "outputField": "item_result"},
            ),
            NodeIR(
                id="merge_1",
                type=NodeType.MERGE,
                label="Merge",
                config={"reducersJson": json.dumps([{"target": "merged_results", "source": "item_result", "reducer": "append"}]), "resultField": "merge_result"},
            ),
            NodeIR(id="reply_1", type=NodeType.DIRECT_REPLY, label="Reply", config={"template": "{{ state.merged_results }}", "outputField": "final_answer"}),
        ]
    )
    project.edges.extend(
        [
            EdgeIR(id="e1", source="start", target="each_1"),
            EdgeIR(id="e2", source="each_1", target="template_1", sourceHandle="item"),
            EdgeIR(id="e3", source="template_1", target="merge_1"),
            EdgeIR(id="e4", source="merge_1", target="reply_1"),
        ]
    )

    export_id, zip_path, files, smoke_test = export_project_zip(project)
    generated = generate_project_files(project)
    nodes_py = next(value for path, value in generated.items() if path.endswith("/nodes.py"))
    graph_py = next(value for path, value in generated.items() if path.endswith("/graph.py"))

    assert export_id
    assert zip_path.exists()
    assert smoke_test.passed
    assert "_run_for_each_node" in nodes_py
    assert "_apply_merge_reducers" in nodes_py
    assert "'template_1': template_1" in nodes_py
    assert 'builder.add_node("template_1"' not in graph_py
    assert 'builder.add_edge("each_1", "reply_1")' in graph_py
    compile(nodes_py, "nodes.py", "exec")
    compile(graph_py, "graph.py", "exec")


def test_codegen_exports_top_level_error_edge_routing():
    project = create_default_project("Top Level Error Export")
    project.state.fields.extend(
        [
            StateField(name="error_result", type="dict"),
            StateField(name="final_answer", type="str"),
        ]
    )
    project.nodes.extend(
        [
            NodeIR(id="bad_template", type=NodeType.TEMPLATE, label="Bad Template", config={"template": "{bad json", "outputType": "json", "outputField": "broken"}),
            NodeIR(id="error_handler", type=NodeType.ERROR_HANDLER, label="Error Handler", config={"errorField": "last_error", "template": "handled", "outputField": "error_result"}),
            NodeIR(id="reply", type=NodeType.DIRECT_REPLY, label="Reply", config={"template": "{{ state.error_result }}", "outputField": "final_answer"}),
        ]
    )
    project.edges.extend(
        [
            EdgeIR(id="e1", source="start", target="bad_template"),
            EdgeIR(id="e2", source="bad_template", target="reply"),
            EdgeIR(id="e3", source="bad_template", target="error_handler", kind=EdgeKind.ERROR, sourceHandle="error"),
            EdgeIR(id="e4", source="error_handler", target="reply"),
        ]
    )

    generated = generate_project_files(project)
    nodes_py = next(value for path, value in generated.items() if path.endswith("/nodes.py"))
    routers_py = next(value for path, value in generated.items() if path.endswith("/routers.py"))
    graph_py = next(value for path, value in generated.items() if path.endswith("/graph.py"))

    assert "def _glg_bad_template_body" in nodes_py
    assert '"_glg_error_from": \'bad_template\'' in nodes_py
    assert "def route_bad_template" in routers_py
    assert 'return "error"' in routers_py
    assert "builder.add_conditional_edges(" in graph_py
    assert '"bad_template"' in graph_py
    assert '"error": "error_handler"' in graph_py
    assert '"__success__": "reply"' in graph_py
    assert 'builder.add_edge("bad_template", "reply")' not in graph_py
    compile(nodes_py, "nodes.py", "exec")
    compile(routers_py, "routers.py", "exec")
    compile(graph_py, "graph.py", "exec")


def test_codegen_exports_runtime_policy_helper_and_parallel_for_each():
    project = create_default_project("Flow v2 Export")
    project.state.fields.extend(
        [
            StateField(name="items", type="list"),
            StateField(name="merged_results", type="list"),
            StateField(name="merge_result", type="dict"),
            StateField(name="final_answer", type="str"),
        ]
    )
    project.nodes.extend(
        [
            NodeIR(
                id="each_1",
                type=NodeType.FOR_EACH,
                label="ForEach",
                config={
                    "itemsField": "items",
                    "itemField": "current_item",
                    "indexField": "current_index",
                    "executionMode": "parallel",
                    "maxConcurrency": 2,
                    "preserveOrder": True,
                    "itemFailurePolicy": "collect_errors",
                    "retryPolicyJson": json.dumps({"enabled": True, "maxRetries": 1, "backoffMs": 0}),
                    "resultField": "for_each_result",
                },
            ),
            NodeIR(id="template_1", type=NodeType.TEMPLATE, label="Template", config={"template": "{{ state.current_item }}", "outputType": "text", "outputField": "item_result"}),
            NodeIR(id="merge_1", type=NodeType.MERGE, label="Merge", config={"reducersJson": json.dumps([{"target": "merged_results", "source": "item_result", "reducer": "append"}]), "resultField": "merge_result"}),
            NodeIR(id="reply_1", type=NodeType.DIRECT_REPLY, label="Reply", config={"template": "{{ state.merged_results }}", "outputField": "final_answer"}),
        ]
    )
    project.edges.extend(
        [
            EdgeIR(id="e1", source="start", target="each_1"),
            EdgeIR(id="e2", source="each_1", target="template_1", sourceHandle="item"),
            EdgeIR(id="e3", source="template_1", target="merge_1"),
            EdgeIR(id="e4", source="merge_1", target="reply_1"),
        ]
    )

    generated = generate_project_files(project)
    nodes_py = next(value for path, value in generated.items() if path.endswith("/nodes.py"))

    assert "_run_node_with_policy" in nodes_py
    assert "def _glg_each_1_body" in nodes_py
    assert '"parallel"' in nodes_py
    assert '"collect_errors"' in nodes_py
    assert "ThreadPoolExecutor" in nodes_py
    compile(nodes_py, "nodes.py", "exec")


def test_codegen_exports_branch_merge_mode():
    project = create_default_project("Branch Merge Export")
    project.state.fields.extend([StateField(name="branch_result", type="str"), StateField(name="merged_branch", type="str"), StateField(name="merge_result", type="dict"), StateField(name="final_answer", type="str")])
    project.nodes.extend(
        [
            NodeIR(id="branch_template", type=NodeType.TEMPLATE, label="Branch", config={"template": "A", "outputType": "text", "outputField": "branch_result"}),
            NodeIR(id="merge_branch", type=NodeType.MERGE, label="Branch Merge", config={"mergeMode": "branch", "reducersJson": json.dumps([{"target": "merged_branch", "source": "branch_result", "reducer": "overwrite"}]), "resultField": "merge_result"}),
            NodeIR(id="reply", type=NodeType.DIRECT_REPLY, label="Reply", config={"template": "{{ state.merged_branch }}", "outputField": "final_answer"}),
        ]
    )
    project.edges.extend(
        [
            EdgeIR(id="e1", source="start", target="branch_template"),
            EdgeIR(id="e2", source="branch_template", target="merge_branch"),
            EdgeIR(id="e3", source="merge_branch", target="reply"),
        ]
    )

    generated = generate_project_files(project)
    nodes_py = next(value for path, value in generated.items() if path.endswith("/nodes.py"))

    assert '_apply_merge_reducers(dict(state), [dict(state)]' in nodes_py
    assert '"branch"' in nodes_py
    assert '"mergeMode": merge_mode' in nodes_py
    compile(nodes_py, "nodes.py", "exec")


def test_exported_flow_control_v2_graph_invokes_smoke():
    project = create_default_project("Flow Control v2 Invoke Smoke")
    project.project.id = "flow_control_v2_invoke_smoke"
    project.state.fields.extend(
        [
            StateField(name="items", type="list"),
            StateField(name="current_item", type="str"),
            StateField(name="current_index", type="int"),
            StateField(name="item_result", type="str"),
            StateField(name="merged_results", type="list"),
            StateField(name="merge_result", type="dict"),
            StateField(name="route", type="str"),
            StateField(name="branch_result", type="str"),
            StateField(name="merged_branch", type="str"),
            StateField(name="branch_merge_result", type="dict"),
            StateField(name="final_answer", type="str"),
        ]
    )
    project.nodes.extend(
        [
            NodeIR(
                id="each",
                type=NodeType.FOR_EACH,
                label="ForEach",
                config={
                    "itemsField": "items",
                    "itemField": "current_item",
                    "indexField": "current_index",
                    "executionMode": "parallel",
                    "maxConcurrency": 2,
                    "preserveOrder": True,
                    "itemFailurePolicy": "collect_errors",
                    "retryPolicyJson": json.dumps({"enabled": True, "maxRetries": 1, "backoffMs": 0}),
                    "resultField": "for_each_result",
                },
            ),
            NodeIR(id="item_template", type=NodeType.TEMPLATE, label="Item", config={"template": "{{ state.current_item }}", "outputType": "text", "outputField": "item_result"}),
            NodeIR(id="foreach_merge", type=NodeType.MERGE, label="ForEach Merge", config={"mergeMode": "for_each", "reducersJson": json.dumps([{"target": "merged_results", "source": "item_result", "reducer": "append"}]), "resultField": "merge_result"}),
            NodeIR(id="condition", type=NodeType.CONDITION, label="Condition", config={"field": "route", "operator": "equals", "value": "a", "trueBranch": "true", "falseBranch": "false", "fallback": "false"}),
            NodeIR(id="branch_a", type=NodeType.TEMPLATE, label="A", config={"template": "A", "outputType": "text", "outputField": "branch_result"}),
            NodeIR(id="branch_b", type=NodeType.TEMPLATE, label="B", config={"template": "B", "outputType": "text", "outputField": "branch_result"}),
            NodeIR(id="branch_merge", type=NodeType.MERGE, label="Branch Merge", config={"mergeMode": "branch", "reducersJson": json.dumps([{"target": "merged_branch", "source": "branch_result", "reducer": "overwrite"}]), "resultField": "branch_merge_result"}),
            NodeIR(id="reply", type=NodeType.DIRECT_REPLY, label="Reply", config={"template": "{{ state.merged_branch }}", "outputField": "final_answer"}),
        ]
    )
    project.edges.extend(
        [
            EdgeIR(id="e1", source="start", target="each"),
            EdgeIR(id="e2", source="each", target="item_template", sourceHandle="item"),
            EdgeIR(id="e3", source="item_template", target="foreach_merge"),
            EdgeIR(id="e4", source="foreach_merge", target="condition"),
            EdgeIR(id="e5", source="condition", target="branch_a", kind=EdgeKind.CONDITIONAL, sourceHandle="true"),
            EdgeIR(id="e6", source="condition", target="branch_b", kind=EdgeKind.CONDITIONAL, sourceHandle="false"),
            EdgeIR(id="e7", source="branch_a", target="branch_merge"),
            EdgeIR(id="e8", source="branch_b", target="branch_merge"),
            EdgeIR(id="e9", source="branch_merge", target="reply"),
        ]
    )

    build_dir, files = build_project(project)
    package = package_name(project)
    script = f"""
from {package}.graph import graph

result = graph.invoke({{"messages": "run", "items": ["a", "b"], "route": "b"}})
assert result["merged_results"] == ["a", "b"], result
assert result["merge_result"]["mergeMode"] == "for_each", result
assert result["branch_merge_result"]["mergeMode"] == "branch", result
assert result["merged_branch"] == "B", result
assert result["final_answer"] == "B", result
"""

    env = {**os.environ, "PYTHONPATH": str(build_dir / "src")}
    completed = subprocess.run([sys.executable, "-c", script], cwd=build_dir, env=env, capture_output=True, text=True, timeout=30, check=False)

    assert "tests/test_graph_smoke.py" in files
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_codegen_embeds_agent_ref_project(monkeypatch):
    child = create_default_project("Child Export Agent")
    child.project.id = "child_export_agent"
    child.nodes.append(NodeIR(id="reply", type=NodeType.DIRECT_REPLY, label="Reply", config={"template": "child: {{ state.messages }}", "outputField": "final_answer"}))
    child.edges.append(EdgeIR(id="child_e1", source="start", target="reply"))

    monkeypatch.setattr("app.compiler.codegen.read_project", lambda project_id: child)

    project = create_default_project("Parent Export Agent")
    project.nodes.append(
        NodeIR(
            id="agent_ref",
            type=NodeType.AGENT_REF,
            label="Child",
            config={"agentProjectId": "child_export_agent", "agentName": "Child Export Agent", "instruction": "处理 {{ state.messages }}"},
        )
    )
    project.edges.append(EdgeIR(id="e1", source="start", target="agent_ref"))

    files = generate_project_files(project)
    nodes_py = next(value for path, value in files.items() if path.endswith(f"{project.project.id}/nodes.py"))
    embedded_py = next(value for path, value in files.items() if path.endswith(f"{project.project.id}/embedded_agents.py"))
    embedded_paths = [path for path in files if "embedded_child_export_agent" in path]

    assert embedded_paths
    assert "run_embedded_agent(project_id" in nodes_py
    assert "child_export_agent" in embedded_py
    assert "导出工程暂不支持" not in nodes_py
    compile(nodes_py, "nodes.py", "exec")
    compile(embedded_py, "embedded_agents.py", "exec")


def test_codegen_embeds_agent_node_selected_project(monkeypatch):
    child = create_default_project("Worker Agent")
    child.project.id = "worker_agent"
    child.nodes.append(NodeIR(id="reply", type=NodeType.DIRECT_REPLY, label="Reply", config={"template": "worker", "outputField": "final_answer"}))
    child.edges.append(EdgeIR(id="child_e1", source="start", target="reply"))

    monkeypatch.setattr("app.compiler.codegen.read_project", lambda project_id: child)

    project = create_default_project("Parent Tool Agent")
    imported = ImportedAgentConfig(id="agent_ref_worker", name="Worker Agent", projectId="worker_agent", role="sub_agent")
    project.importedAgents.append(imported)
    project.nodes.append(
        NodeIR(
            id="agent_1",
            type=NodeType.AGENT,
            label="Agent",
            config={
                "agentIdsJson": '["agent_ref_worker"]',
                "agentRegistryJson": json.dumps([imported.model_dump(by_alias=True)], ensure_ascii=False),
                "outputField": "answer",
            },
        )
    )
    project.edges.append(EdgeIR(id="e1", source="start", target="agent_1"))

    files = generate_project_files(project)
    nodes_py = next(value for path, value in files.items() if path.endswith(f"{project.project.id}/nodes.py"))
    embedded_py = next(value for path, value in files.items() if path.endswith(f"{project.project.id}/embedded_agents.py"))

    assert "selected_embedded_agent_tool_configs" in nodes_py
    assert "answer_agent_tool_calls" in nodes_py
    assert "worker_agent" in embedded_py
    assert "导出工程暂不支持" not in nodes_py
    compile(nodes_py, "nodes.py", "exec")


def test_codegen_rejects_embedded_agent_cycle(monkeypatch):
    root = create_default_project("Root Cycle")
    root.project.id = "root_cycle"
    child = create_default_project("Child Cycle")
    child.project.id = "child_cycle"
    child.nodes.append(NodeIR(id="ref_root", type=NodeType.AGENT_REF, label="Root", config={"agentProjectId": "root_cycle"}))
    child.edges.append(EdgeIR(id="child_e1", source="start", target="ref_root"))
    root.nodes.append(NodeIR(id="ref_child", type=NodeType.AGENT_REF, label="Child", config={"agentProjectId": "child_cycle"}))
    root.edges.append(EdgeIR(id="e1", source="start", target="ref_child"))

    def fake_read_project(project_id):
        return child if project_id == "child_cycle" else root

    monkeypatch.setattr("app.compiler.codegen.read_project", fake_read_project)

    try:
        generate_project_files(root)
    except RuntimeError as exc:
        assert "循环引用" in str(exc)
    else:
        raise AssertionError("expected cycle export error")


def test_codegen_converts_direct_mcp_api_key_to_env_placeholder():
    project = create_default_project("MCP Direct Secret Export")
    project.mcpServers.append(
        MCPServerConfig(
            id="exa",
            name="Exa MCP",
            transport="http",
            url="https://mcp.exa.ai/mcp",
            apiKeyMode="direct",
            apiKey="direct-secret",
            apiKeyHeader="x-api-key",
            apiKeyPrefix="",
        )
    )

    files = generate_project_files(project)
    mcp_servers_py = next(value for path, value in files.items() if path.endswith("/mcp_servers.py"))

    assert "direct-secret" not in mcp_servers_py
    assert "EXA_MCP_API_KEY=replace_me" in files[".env.example"]
    assert '"apiKeyMode": "env"' in mcp_servers_py
    assert '"apiKeyHeader": "x-api-key"' in mcp_servers_py


def test_codegen_sanitizes_mcp_snapshot_json_in_export_graph():
    project = create_default_project("MCP Snapshot Secret Export")
    snapshot = MCPServerConfig(
        id="exa",
        name="Exa MCP",
        transport="http",
        url="https://mcp.exa.ai/mcp",
        apiKeyMode="direct",
        apiKey="snapshot-secret",
        apiKeyHeader="x-api-key",
        apiKeyPrefix="",
        httpHeadersJson='{"x-api-key":"header-secret","X-Figma-Region":"us-east-1"}',
    ).model_dump(by_alias=True)
    project.nodes.append(
        NodeIR(
            id="mcp_snapshot",
            type=NodeType.MCP_NODE,
            label="Exa Snapshot",
            config={
                "serverId": "exa",
                "serverName": "Exa MCP",
                "mcpServerSnapshotJson": json.dumps([snapshot]),
                "toolName": "web_search_exa",
            },
        )
    )
    project.edges.append(EdgeIR(id="e1", source="start", target="mcp_snapshot"))

    files = generate_project_files(project)
    mcp_servers_py = next(value for path, value in files.items() if path.endswith("/mcp_servers.py"))
    flow_json = files["flow/project.graph.json"]

    assert "snapshot-secret" not in mcp_servers_py
    assert "snapshot-secret" not in flow_json
    assert "header-secret" not in mcp_servers_py
    assert "header-secret" not in flow_json
    assert "EXA_MCP_API_KEY=replace_me" in files[".env.example"]
    assert "EXA_MCP_X_API_KEY=replace_me" in files[".env.example"]
    assert '"apiKeyMode": "env"' in mcp_servers_py
    assert '"envHttpHeadersJson": "{\\"x-api-key\\": \\"EXA_MCP_X_API_KEY\\"}"' in mcp_servers_py
    assert "us-east-1" in mcp_servers_py


def test_codegen_converts_sensitive_mcp_static_headers_to_env():
    project = create_default_project("MCP Header Secret Export")
    project.mcpServers.append(
        MCPServerConfig(
            id="exa",
            name="Exa MCP",
            transport="http",
            url="https://mcp.exa.ai/mcp",
            httpHeadersJson='{"x-api-key":"direct-header-secret","X-Figma-Region":"us-east-1"}',
        )
    )

    files = generate_project_files(project)
    mcp_servers_py = next(value for path, value in files.items() if path.endswith("/mcp_servers.py"))
    flow_json = files["flow/project.graph.json"]

    assert "direct-header-secret" not in mcp_servers_py
    assert "direct-header-secret" not in flow_json
    assert "EXA_MCP_X_API_KEY=replace_me" in files[".env.example"]
    assert '"httpHeadersJson": "{\\"X-Figma-Region\\": \\"us-east-1\\"}"' in mcp_servers_py
    assert '"envHttpHeadersJson": "{\\"x-api-key\\": \\"EXA_MCP_X_API_KEY\\"}"' in mcp_servers_py


def test_codegen_converts_sensitive_mcp_stdio_env_to_env_vars():
    project = create_default_project("MCP Stdio Env Secret Export")
    project.mcpServers.append(
        MCPServerConfig(
            id="local_exa",
            name="Local Exa MCP",
            transport="stdio",
            command="npx",
            argsJson='["-y","exa-mcp-server"]',
            envJson='{"EXA_API_KEY":"stdio-secret","LOG_LEVEL":"debug"}',
        )
    )

    files = generate_project_files(project)
    mcp_servers_py = next(value for path, value in files.items() if path.endswith("/mcp_servers.py"))
    flow_json = files["flow/project.graph.json"]

    assert "stdio-secret" not in mcp_servers_py
    assert "stdio-secret" not in flow_json
    assert "EXA_API_KEY=replace_me" in files[".env.example"]
    assert '"envJson": "{\\"LOG_LEVEL\\": \\"debug\\"}"' in mcp_servers_py
    assert '"envVarsJson": "[\\"EXA_API_KEY\\"]"' in mcp_servers_py


def test_codegen_supports_mvp_nodes():
    project = create_default_project("MVP Agent")
    project.state.fields.extend(
        [
            StateField(name="route_key", type="str"),
            StateField(name="retrieved_context", type="str"),
            StateField(name="agent_result", type="str"),
        ]
    )
    project.nodes.extend(
        [
            NodeIR(
                id="router_1",
                type=NodeType.AI_ROUTER,
                label="路由",
                config={"routeField": "route_key", "fallback": "other", "scenarios": "other:其他问题:"},
            ),
            NodeIR(
                id="retriever_1",
                type=NodeType.RETRIEVER,
                label="检索",
                config={"outputField": "retrieved_context", "path": "./knowledge"},
            ),
            NodeIR(
                id="agent_1",
                type=NodeType.AGENT,
                label="Agent",
                config={"outputField": "agent_result", "maxIterations": 2},
            ),
            NodeIR(id="reply_1", type=NodeType.DIRECT_REPLY, label="回复", config={"template": "{{ state.agent_result }}"}),
        ]
    )
    project.edges.extend(
        [
            EdgeIR(id="e1", source="start", target="router_1"),
            EdgeIR(id="e2", source="router_1", sourceHandle="other", target="retriever_1", kind=EdgeKind.CONDITIONAL),
            EdgeIR(id="e3", source="retriever_1", target="agent_1"),
            EdgeIR(id="e4", source="agent_1", target="reply_1"),
        ]
    )

    files = generate_project_files(project)
    nodes_py = next(value for path, value in files.items() if path.endswith("/nodes.py"))
    routers_py = next(value for path, value in files.items() if path.endswith("/routers.py"))

    assert "def router_1" in nodes_py
    assert "def retriever_1" in nodes_py
    assert "def agent_1" in nodes_py
    assert "def route_router_1" in routers_py


def test_codegen_human_approval_uses_interrupt_and_checkpointer():
    project = create_default_project("审批 Agent")
    project.state.fields.extend(
        [
            StateField(name="approval_action", type="str"),
            StateField(name="approval_result", type="dict"),
        ]
    )
    project.nodes.extend(
        [
            NodeIR(
                id="approval_1",
                type=NodeType.HUMAN_APPROVAL,
                label="审批",
                config={"fallback": "rejected", "actionField": "approval_action", "outputField": "approval_result"},
            ),
            NodeIR(id="reply_1", type=NodeType.DIRECT_REPLY, label="回复"),
        ]
    )
    project.edges.extend(
        [
            EdgeIR(id="e1", source="start", target="approval_1"),
            EdgeIR(id="e2", source="approval_1", sourceHandle="approved", target="reply_1", kind=EdgeKind.CONDITIONAL),
            EdgeIR(id="e3", source="approval_1", sourceHandle="rejected", target="reply_1", kind=EdgeKind.CONDITIONAL),
            EdgeIR(id="e4", source="approval_1", sourceHandle="edit", target="reply_1", kind=EdgeKind.CONDITIONAL),
        ]
    )

    files = generate_project_files(project)
    nodes_py = next(value for path, value in files.items() if path.endswith("/nodes.py"))
    graph_py = next(value for path, value in files.items() if path.endswith("/graph.py"))
    readme = files["README.md"]

    assert "interrupt(payload)" in nodes_py
    assert '"actions": ["approved", "rejected", "edit"]' in nodes_py
    assert "InMemorySaver" in graph_py
    assert "compile(checkpointer=checkpointer)" in graph_py
    assert "Human approval resume" in readme
    assert "Command(resume=" in readme
    assert '"action": "approved"' in readme


def test_codegen_sanitizes_flow_project_json():
    project = sample_project()
    project.nodes[1].config["apiKey"] = "sk-test"

    files = generate_project_files(project)
    flow_json = files["flow/project.graph.json"]

    assert "sk-test" not in flow_json
    assert '"apiKey": ""' in flow_json


def test_codegen_http_node_preserves_mock_response():
    project = create_default_project("HTTP Mock Agent")
    project.state.fields.extend([StateField(name="http_response", type="dict"), StateField(name="final_answer", type="str")])
    project.nodes.extend(
        [
            NodeIR(
                id="http_1",
                type=NodeType.HTTP,
                label="HTTP Mock",
                config={
                    "mockEnabled": True,
                    "mockResponseJson": '{"status":"ok","order_id":"{{ state.order_id }}"}',
                    "outputField": "http_response",
                },
            ),
            NodeIR(id="reply_1", type=NodeType.DIRECT_REPLY, label="回复", config={"template": "{{ state.http_response }}"}),
        ]
    )
    project.edges.extend(
        [
            EdgeIR(id="e1", source="start", target="http_1"),
            EdgeIR(id="e2", source="http_1", target="reply_1"),
        ]
    )

    files = generate_project_files(project)
    nodes_py = next(value for path, value in files.items() if path.endswith("/nodes.py"))

    assert "_render_json_template" in nodes_py
    assert "mockEnabled" not in nodes_py
    assert "status" in nodes_py
    assert "ok" in nodes_py


def test_codegen_exports_phase1_code_reading_tools():
    project = create_default_project("Code Tools Agent")
    for builtin_id, name in [
        ("task_plan", "task_plan"),
        ("read_file_chunk", "read_file_chunk"),
        ("search_code", "search_code"),
        ("list_code_symbols", "list_code_symbols"),
    ]:
        project.tools.append(
            ToolConfig(
                id=f"builtin_{builtin_id}",
                name=name,
                description=name,
                source="builtin",
                schemaJson=f'{{"type":"object","x-graphic":{{"kind":"builtin_tool","builtinId":"{builtin_id}"}}}}',
            )
        )

    files = generate_project_files(project)
    tools_py = next(value for path, value in files.items() if path.endswith("/tools.py"))

    assert "def task_plan" in tools_py
    assert "task_splitter_v1" in tools_py
    assert "def read_file_chunk" in tools_py
    assert "def search_code" in tools_py
    assert "def list_code_symbols" in tools_py
    assert "glg_semantic_symbols(text, detected, max_symbols)" in tools_py
    assert "def _glg_single_file_component_symbols" in tools_py
    assert "'vue': 'vue'" in tools_py
    assert "'md': 'markdown'" in tools_py
    assert "CODE_TOOL_EXCLUDED_DIRS" in tools_py
    assert "tree-sitter>=0.25.0" in files["pyproject.toml"]
    assert "tree-sitter-language-pack>=1.8.0" in files["pyproject.toml"]
    compile(tools_py, "tools.py", "exec")


def test_codegen_exports_phase2_html_css_tools_with_dependency():
    project = create_default_project("HTML CSS Tools Agent")
    for builtin_id, name in [
        ("extract_html", "extract_html"),
        ("extract_css_rules", "extract_css_rules"),
    ]:
        project.tools.append(
            ToolConfig(
                id=f"builtin_{builtin_id}",
                name=name,
                description=name,
                source="builtin",
                schemaJson=f'{{"type":"object","x-graphic":{{"kind":"builtin_tool","builtinId":"{builtin_id}"}}}}',
            )
        )

    files = generate_project_files(project)
    tools_py = next(value for path, value in files.items() if path.endswith("/tools.py"))

    assert "def extract_html" in tools_py
    assert "def extract_css_rules" in tools_py
    assert "beautifulsoup4>=4.12.0" in files["pyproject.toml"]
    assert "GLG_FILE_TOOL_ROOTS" in files[".env.example"]
    assert "HTML, and CSS tools" in files["README.md"]
    compile(tools_py, "tools.py", "exec")


def test_codegen_exports_phase3_structured_code_tools_with_dependencies():
    project = create_default_project("Structured Code Tools Agent")
    for builtin_id, name in [
        ("extract_code_symbol", "extract_code_symbol"),
        ("chunk_code_semantic", "chunk_code_semantic"),
    ]:
        project.tools.append(
            ToolConfig(
                id=f"builtin_{builtin_id}",
                name=name,
                description=name,
                source="builtin",
                schemaJson=f'{{"type":"object","x-graphic":{{"kind":"builtin_tool","builtinId":"{builtin_id}"}}}}',
            )
        )

    files = generate_project_files(project)
    tools_py = next(value for path, value in files.items() if path.endswith("/tools.py"))

    assert "def extract_code_symbol" in tools_py
    assert "def chunk_code_semantic" in tools_py
    assert "def glg_extract_code_symbol" in tools_py
    assert "def _glg_single_file_component_symbols" in tools_py
    assert "'vue': 'vue'" in tools_py
    assert "'md': 'markdown'" in tools_py
    assert "tree-sitter>=0.25.0" in files["pyproject.toml"]
    assert "tree-sitter-language-pack>=1.8.0" in files["pyproject.toml"]
    assert "GLG_FILE_TOOL_ROOTS" in files[".env.example"]
    compile(tools_py, "tools.py", "exec")


def test_codegen_exports_phase5_page_tools_with_dependency():
    project = create_default_project("Page Tools Agent")
    for builtin_id, name in [
        ("extract_html_by_text", "extract_html_by_text"),
        ("extract_css_for_html", "extract_css_for_html"),
        ("summarize_page_structure", "summarize_page_structure"),
        ("resolve_asset_references", "resolve_asset_references"),
    ]:
        project.tools.append(
            ToolConfig(
                id=f"builtin_{builtin_id}",
                name=name,
                description=name,
                source="builtin",
                schemaJson=f'{{"type":"object","x-graphic":{{"kind":"builtin_tool","builtinId":"{builtin_id}"}}}}',
            )
        )

    files = generate_project_files(project)
    tools_py = next(value for path, value in files.items() if path.endswith("/tools.py"))

    assert "def extract_html_by_text" in tools_py
    assert "def extract_css_for_html" in tools_py
    assert "def summarize_page_structure" in tools_py
    assert "def resolve_asset_references" in tools_py
    assert "def glg_extract_html_by_text" in tools_py
    assert "def _enrich_asset_reference" in tools_py
    assert "beautifulsoup4>=4.12.0" in files["pyproject.toml"]
    assert "GLG_FILE_TOOL_ROOTS" in files[".env.example"]
    compile(tools_py, "tools.py", "exec")


def test_codegen_exports_task_splitter_and_parallel_tools():
    project = create_default_project("Parallel Coder Reader")
    project.state.fields.extend(
        [
            StateField(name="task_plan", type="str"),
            StateField(name="worker_tasks", type="list"),
            StateField(name="worker_results", type="list"),
            StateField(name="final_answer", type="str"),
        ]
    )
    project.tools.append(
        ToolConfig(
            id="builtin_search_code",
            name="search_code",
            description="search_code",
            source="builtin",
            schemaJson='{"type":"object","x-graphic":{"kind":"builtin_tool","builtinId":"search_code"}}',
        )
    )
    project.nodes.extend(
        [
            NodeIR(id="splitter_1", type=NodeType.TASK_SPLITTER, label="拆分任务", config={"inputField": "task_plan", "outputField": "worker_tasks"}),
            NodeIR(
                id="parallel_1",
                type=NodeType.PARALLEL_TOOLS,
                label="并行 Worker",
                config={
                    "tasksField": "worker_tasks",
                    "outputField": "worker_results",
                    "toolIdsJson": '["builtin_search_code"]',
                    "toolRegistryJson": f"[{project.tools[0].model_dump_json(by_alias=True)}]",
                    "maxConcurrentWorkers": 3,
                    "maxIterationsPerTask": 4,
                },
            ),
            NodeIR(id="worker_1", type=NodeType.PARALLEL_WORKER, label="Worker 1", config={"parentNodeId": "parallel_1", "workerIndex": 1}),
            NodeIR(id="worker_2", type=NodeType.PARALLEL_WORKER, label="Worker 2", config={"parentNodeId": "parallel_1", "workerIndex": 2}),
            NodeIR(id="reply_1", type=NodeType.DIRECT_REPLY, label="回复", config={"template": "{{ state.worker_results }}", "outputField": "final_answer"}),
        ]
    )
    project.edges.extend(
        [
            EdgeIR(id="e1", source="start", target="splitter_1"),
            EdgeIR(id="e2", source="splitter_1", target="parallel_1"),
            EdgeIR(id="ew1", source="parallel_1", target="worker_1", kind=EdgeKind.WORKER),
            EdgeIR(id="ew2", source="parallel_1", target="worker_2", kind=EdgeKind.WORKER),
            EdgeIR(id="ewo1", source="worker_1", target="reply_1", kind=EdgeKind.WORKER),
            EdgeIR(id="ewo2", source="worker_2", target="reply_1", kind=EdgeKind.WORKER),
        ]
    )

    files = generate_project_files(project)
    nodes_py = next(value for path, value in files.items() if path.endswith("/nodes.py"))

    assert "def splitter_1" in nodes_py
    assert "def parallel_1" in nodes_py
    assert "def worker_1" not in nodes_py
    assert 'builder.add_edge("parallel_1", "reply_1")' in next(value for path, value in files.items() if path.endswith("/graph.py"))
    assert "ThreadPoolExecutor" in nodes_py
    assert "_run_export_worker_task" in nodes_py
    assert "_normalize_worker_tasks" in nodes_py
    compile(nodes_py, "nodes.py", "exec")
