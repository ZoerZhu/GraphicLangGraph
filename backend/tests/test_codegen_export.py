import zipfile

from app.compiler import export_project_zip, generate_project_files
from app.ir.schemas import EdgeIR, EdgeKind, NodeIR, NodeType, Position, StateField, ToolConfig, create_default_project


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
        ]
    )

    files = generate_project_files(project)
    nodes_py = next(value for path, value in files.items() if path.endswith("/nodes.py"))
    graph_py = next(value for path, value in files.items() if path.endswith("/graph.py"))

    assert "interrupt(payload)" in nodes_py
    assert "InMemorySaver" in graph_py
    assert "compile(checkpointer=checkpointer)" in graph_py


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
            NodeIR(id="reply_1", type=NodeType.DIRECT_REPLY, label="回复", config={"template": "{{ state.worker_results }}", "outputField": "final_answer"}),
        ]
    )
    project.edges.extend(
        [
            EdgeIR(id="e1", source="start", target="splitter_1"),
            EdgeIR(id="e2", source="splitter_1", target="parallel_1"),
            EdgeIR(id="e3", source="parallel_1", target="reply_1"),
        ]
    )

    files = generate_project_files(project)
    nodes_py = next(value for path, value in files.items() if path.endswith("/nodes.py"))

    assert "def splitter_1" in nodes_py
    assert "def parallel_1" in nodes_py
    assert "ThreadPoolExecutor" in nodes_py
    assert "_run_export_worker_task" in nodes_py
    assert "_normalize_worker_tasks" in nodes_py
    compile(nodes_py, "nodes.py", "exec")
