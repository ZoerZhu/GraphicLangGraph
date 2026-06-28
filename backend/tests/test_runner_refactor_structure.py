import importlib
from pathlib import Path

from app.ir.schemas import NodeType
from app.runner import registry


NODE_MODULES = [
    "agent",
    "agent_ref",
    "ai_router",
    "condition",
    "direct_reply",
    "error_handler",
    "for_each",
    "http",
    "human_approval",
    "json_extractor",
    "json_validator",
    "llm",
    "mcp_node",
    "merge",
    "parallel_tools",
    "retriever",
    "skill_node",
    "task_splitter",
    "template",
    "tool",
    "variable_assign",
]


def test_node_executor_modules_import_without_cycles():
    for module_name in NODE_MODULES:
        module = importlib.import_module(f"app.runner.nodes.{module_name}")
        assert hasattr(module, "execute_live")


def test_registry_covers_executable_node_types():
    executable = {
        NodeType.AGENT,
        NodeType.AGENT_REF,
        NodeType.AI_ROUTER,
        NodeType.CONDITION,
        NodeType.DIRECT_REPLY,
        NodeType.ERROR_HANDLER,
        NodeType.FOR_EACH,
        NodeType.HTTP,
        NodeType.HUMAN_APPROVAL,
        NodeType.JSON_EXTRACTOR,
        NodeType.JSON_VALIDATOR,
        NodeType.LLM,
        NodeType.MCP_NODE,
        NodeType.MERGE,
        NodeType.PARALLEL_TOOLS,
        NodeType.RETRIEVER,
        NodeType.SKILL_NODE,
        NodeType.TASK_SPLITTER,
        NodeType.TEMPLATE,
        NodeType.TOOL,
        NodeType.VARIABLE_ASSIGN,
    }
    assert registry.covered_node_types() == executable


def test_preview_facade_does_not_define_node_executors():
    preview_path = Path(__file__).parents[1] / "app" / "runner" / "preview.py"
    source = preview_path.read_text(encoding="utf-8")
    assert "def _execute_live_" not in source
    assert "def _execute_dry_node" not in source
    assert "def _invoke_registered_tool" not in source


def test_engine_facade_does_not_define_graph_walk_or_node_executors():
    engine_path = Path(__file__).parents[1] / "app" / "runner" / "engine.py"
    source = engine_path.read_text(encoding="utf-8")
    assert "def _walk_project" not in source
    assert "def walk_project" not in source
    assert "def _resume_project" not in source
    assert "def _execute_live_node" not in source
    assert "def execute_live_node" not in source
