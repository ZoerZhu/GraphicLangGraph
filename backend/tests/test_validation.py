from app.ir.schemas import EdgeIR, EdgeKind, NodeIR, NodeType, Position, ProjectIR, StateField, create_default_project
from app.ir.validation import validate_project


def test_valid_minimal_graph():
    project = create_default_project()
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
    assert any(issue.code == "CONDITION_BRANCH_EDGE" for issue in result.issues)


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
    assert any(issue.code == "ROUTER_BRANCH_EDGE" for issue in result.issues)


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


def test_validates_for_each_requires_merge_and_rejects_nested_flow():
    project = create_default_project("Bad ForEach")
    project.state.fields.extend([StateField(name="items", type="list"), StateField(name="final_answer", type="str")])
    project.nodes.extend(
        [
            NodeIR(id="each", type=NodeType.FOR_EACH, label="ForEach", config={"itemsField": "items", "itemField": "item", "indexField": "index"}),
            NodeIR(id="nested_each", type=NodeType.FOR_EACH, label="Nested", config={"itemsField": "items", "itemField": "item2", "indexField": "index2"}),
            NodeIR(id="reply", type=NodeType.DIRECT_REPLY, label="Reply", config={"template": "done", "outputField": "final_answer"}),
        ]
    )
    project.edges.extend(
        [
            EdgeIR(id="e1", source="start", target="each"),
            EdgeIR(id="e2", source="each", target="nested_each", sourceHandle="item"),
            EdgeIR(id="e3", source="nested_each", target="reply", sourceHandle="item"),
        ]
    )

    result = validate_project(project)

    assert not result.valid
    assert any(issue.code == "FOR_EACH_MERGE_REQUIRED" for issue in result.issues)
    assert any(issue.code == "FOR_EACH_NESTED_UNSUPPORTED" for issue in result.issues)


def test_validates_merge_reducers():
    project = create_default_project("Bad Merge")
    project.state.fields.extend([StateField(name="items", type="list"), StateField(name="final_answer", type="str")])
    project.nodes.extend(
        [
            NodeIR(id="each", type=NodeType.FOR_EACH, label="ForEach", config={"itemsField": "items", "itemField": "item", "indexField": "index"}),
            NodeIR(id="merge", type=NodeType.MERGE, label="Merge", config={"reducersJson": '[{"target":"","source":"","reducer":"sum"}]'}),
            NodeIR(id="reply", type=NodeType.DIRECT_REPLY, label="Reply", config={"template": "done", "outputField": "final_answer"}),
        ]
    )
    project.edges.extend(
        [
            EdgeIR(id="e1", source="start", target="each"),
            EdgeIR(id="e2", source="each", target="merge", sourceHandle="item"),
            EdgeIR(id="e3", source="merge", target="reply"),
        ]
    )

    result = validate_project(project)

    assert not result.valid
    assert any(issue.code == "MERGE_REDUCER_TARGET" for issue in result.issues)
    assert any(issue.code == "MERGE_REDUCER_SOURCE" for issue in result.issues)
    assert any(issue.code == "MERGE_REDUCER_OPERATION" for issue in result.issues)


def test_rejects_undeclared_state_write():
    project = create_default_project()
    project.nodes.extend(
        [
            NodeIR(id="llm_1", type=NodeType.LLM, label="生成", config={"outputField": "final_answer"}),
            NodeIR(id="reply_1", type=NodeType.DIRECT_REPLY, label="回复", config={"template": "{{ state.final_answer }}"}),
        ]
    )
    project.edges.extend(
        [
            EdgeIR(id="e1", source="start", target="llm_1"),
            EdgeIR(id="e2", source="llm_1", target="reply_1"),
        ]
    )

    result = validate_project(project)

    assert not result.valid
    assert any(issue.code == "STATE_FIELD_UNDECLARED" and issue.field == "final_answer" for issue in result.issues)


def test_rejects_missing_conditional_source_handle():
    project = create_default_project()
    project.nodes.extend(
        [
            NodeIR(
                id="router_1",
                type=NodeType.AI_ROUTER,
                label="路由",
                config={"fallback": "other", "scenarios": "other:其他问题:"},
                outputs=[{"id": "other", "type": "condition", "label": "其他"}],
            ),
            NodeIR(id="reply_1", type=NodeType.DIRECT_REPLY, label="回复"),
        ]
    )
    project.edges.extend(
        [
            EdgeIR(id="e1", source="start", target="router_1"),
            EdgeIR(id="e2", source="router_1", target="reply_1", kind=EdgeKind.CONDITIONAL),
        ]
    )

    result = validate_project(project)

    assert not result.valid
    assert any(issue.code == "CONDITIONAL_EDGE_HANDLE" for issue in result.issues)


def test_rejects_plaintext_secret_in_node_config():
    project = create_default_project()
    project.state.fields.append(StateField(name="final_answer", type="str"))
    project.nodes.extend(
        [
            NodeIR(id="llm_1", type=NodeType.LLM, label="生成", config={"outputField": "final_answer", "apiKey": "sk-test"}),
            NodeIR(id="reply_1", type=NodeType.DIRECT_REPLY, label="回复", config={"template": "{{ state.final_answer }}"}),
        ]
    )
    project.edges.extend(
        [
            EdgeIR(id="e1", source="start", target="llm_1"),
            EdgeIR(id="e2", source="llm_1", target="reply_1"),
        ]
    )

    result = validate_project(project)

    assert not result.valid
    assert any(issue.code == "PLAINTEXT_SECRET" for issue in result.issues)


def test_rejects_reachable_node_without_terminal_path():
    project = create_default_project()
    project.nodes.extend(
        [
            NodeIR(id="custom_1", type=NodeType.CUSTOM_FUNCTION, label="函数", config={"code": "return {}"}),
            NodeIR(id="reply_1", type=NodeType.DIRECT_REPLY, label="回复"),
        ]
    )
    project.edges.append(EdgeIR(id="e1", source="start", target="custom_1"))

    result = validate_project(project)

    assert not result.valid
    assert any(issue.code == "NO_TERMINAL_PATH" and issue.nodeId == "custom_1" for issue in result.issues)
