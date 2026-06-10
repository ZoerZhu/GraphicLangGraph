import zipfile

from app.compiler import export_project_zip, generate_project_files
from app.ir.schemas import EdgeIR, NodeIR, NodeType, Position, StateField, create_default_project


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

