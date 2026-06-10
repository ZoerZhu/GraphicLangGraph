from app.ir.schemas import EdgeIR, EdgeKind, NodeIR, NodeType, Position, ProjectIR, create_default_project
from app.ir.validation import validate_project


def test_valid_minimal_graph():
    project = create_default_project()
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

    result = validate_project(project)

    assert result.valid


def test_rejects_missing_start():
    project = ProjectIR()
    project.nodes.append(NodeIR(id="reply", type=NodeType.DIRECT_REPLY, label="回复"))

    result = validate_project(project)

    assert not result.valid
    assert any(issue.code == "START_COUNT" for issue in result.issues)


def test_rejects_condition_without_fallback_edge():
    project = create_default_project()
    project.nodes.extend(
        [
            NodeIR(
                id="condition_1",
                type=NodeType.CONDITION,
                label="判断",
                config={"field": "intent", "fallback": "fallback"},
            ),
            NodeIR(id="reply_1", type=NodeType.DIRECT_REPLY, label="回复"),
        ]
    )
    project.edges.extend(
        [
            EdgeIR(id="e1", source="start", target="condition_1"),
            EdgeIR(
                id="e2",
                source="condition_1",
                sourceHandle="true",
                target="reply_1",
                kind=EdgeKind.CONDITIONAL,
            ),
        ]
    )

    result = validate_project(project)

    assert not result.valid
    assert any(issue.code == "CONDITION_FALLBACK_EDGE" for issue in result.issues)


def test_rejects_custom_function_syntax_error():
    project = create_default_project()
    project.nodes.extend(
        [
            NodeIR(
                id="custom_1",
                type=NodeType.CUSTOM_FUNCTION,
                label="函数",
                config={"code": "return {"},
            ),
            NodeIR(id="reply_1", type=NodeType.DIRECT_REPLY, label="回复"),
        ]
    )
    project.edges.extend(
        [
            EdgeIR(id="e1", source="start", target="custom_1"),
            EdgeIR(id="e2", source="custom_1", target="reply_1"),
        ]
    )

    result = validate_project(project)

    assert not result.valid
    assert any(issue.code == "CUSTOM_FUNCTION_SYNTAX" for issue in result.issues)


def test_rejects_ai_router_without_fallback_edge():
    project = create_default_project()
    project.nodes.extend(
        [
            NodeIR(
                id="router_1",
                type=NodeType.AI_ROUTER,
                label="路由",
                config={"fallback": "other", "scenarios": "order:订单问题:订单\nother:其他问题:"},
                outputs=[
                    {"id": "order", "type": "condition", "label": "订单"},
                    {"id": "other", "type": "condition", "label": "其他"},
                ],
            ),
            NodeIR(id="reply_1", type=NodeType.DIRECT_REPLY, label="回复"),
        ]
    )
    project.edges.extend(
        [
            EdgeIR(id="e1", source="start", target="router_1"),
            EdgeIR(id="e2", source="router_1", sourceHandle="order", target="reply_1", kind=EdgeKind.CONDITIONAL),
        ]
    )

    result = validate_project(project)

    assert not result.valid
    assert any(issue.code == "ROUTER_FALLBACK_EDGE" for issue in result.issues)


def test_rejects_invalid_tool_params_json():
    project = create_default_project()
    project.nodes.extend(
        [
            NodeIR(id="tool_1", type=NodeType.TOOL, label="工具", config={"paramsJson": "{"}),
            NodeIR(id="reply_1", type=NodeType.DIRECT_REPLY, label="回复"),
        ]
    )
    project.edges.extend(
        [
            EdgeIR(id="e1", source="start", target="tool_1"),
            EdgeIR(id="e2", source="tool_1", target="reply_1"),
        ]
    )

    result = validate_project(project)

    assert not result.valid
    assert any(issue.code == "TOOL_PARAMS_JSON" for issue in result.issues)
