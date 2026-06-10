import zipfile

from app.compiler import export_project_zip, generate_project_files
from app.ir.schemas import EdgeIR, EdgeKind, NodeIR, NodeType, Position, StateField, create_default_project


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
    export_id, zip_path, files = export_project_zip(sample_project())

    assert export_id
    assert zip_path.exists()
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
