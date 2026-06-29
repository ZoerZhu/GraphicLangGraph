import json
from pathlib import Path

from app.ir.schemas import EdgeIR, EdgeKind, NodeIR, NodeType, Position, StateField, create_default_project
from app.ir.validation import validate_project
from app.runner import preview
from app.runner import model_runtime


class FakeResponse:
    def __init__(self, content: str):
        self.content = content


def test_complex_enterprise_ops_agent_validates_and_runs_batch_path():
    project = complex_enterprise_ops_agent()

    validation = validate_project(project)
    assert validation.valid, [issue.model_dump() for issue in validation.issues]

    trace, state = preview.run_project_preview(
        project,
        {"messages": "请批量处理退款政策核对、订单核验和风险审批建议。"},
        "dry",
    )

    trace_ids = [item["nodeId"] for item in trace]
    assert "extract_request" in trace_ids
    assert "validate_request" in trace_ids
    assert "retrieve_policy" in trace_ids
    assert "route_request" in trace_ids
    assert "split_tasks" in trace_ids
    assert "iterate_tasks" in trace_ids
    assert trace_ids[-1] == "reply_final"
    assert state["route_key"] == "batch"
    assert len(state["worker_tasks"]) == 3
    assert len(state["worker_results"]) == 3
    assert state["merge_result"]["mergeMode"] == "for_each"
    assert len(state["merge_result"]["iterations"]) == 3
    assert state["final_answer"]


def test_complex_enterprise_ops_agent_live_refund_path_pauses_and_resumes(monkeypatch, tmp_path: Path):
    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()
    (knowledge_dir / "refund.md").write_text("退款政策：高风险退款需要人工审批。", encoding="utf-8")

    calls: list[list[tuple[str, str]]] = []

    def fake_call_chat_model(provider, model, messages, runtime_config=None):
        calls.append(messages)
        if messages and "JSON Extractor" in messages[0][1]:
            return FakeResponse(
                json.dumps(
                    {
                        "intent": "refund",
                        "orderId": "ORDER-REFUND-001",
                        "riskLevel": "high",
                        "tasks": [{"title": "退款政策核对", "goal": "确认退款是否需要人工审批"}],
                    },
                    ensure_ascii=False,
                )
            )
        return FakeResponse("退款审批已通过，已结合知识库政策生成最终处理建议。")

    monkeypatch.setattr(model_runtime, "call_chat_model", fake_call_chat_model)

    project = complex_enterprise_ops_agent(str(knowledge_dir))
    trace, state = preview.run_project_preview(
        project,
        {"messages": "我要申请一笔高风险退款", "order_id": "ORDER-REFUND-001"},
        "live",
        {"provider": "openai", "model": "gpt-4.1-mini", "enabled": True},
    )

    assert [item["nodeId"] for item in trace][-1] == "refund_approval"
    assert state["route_key"] == "refund"
    assert state["_glg_run_status"] == "paused"
    assert state["_glg_pending_approval"]["nodeId"] == "refund_approval"

    resumed_trace, resumed_state = preview.resume_project_preview(
        project,
        state,
        "refund_approval",
        "approved",
        "同意退款",
        "live",
        {"provider": "openai", "model": "gpt-4.1-mini", "enabled": True},
    )

    assert [item["nodeId"] for item in resumed_trace] == ["refund_approval", "final_agent", "reply_final"]
    assert resumed_state["approval_action"] == "approved"
    assert resumed_state["approval_result"]["comment"] == "同意退款"
    assert "退款审批已通过" in resumed_state["final_answer"]
    assert len(calls) == 2


def complex_enterprise_ops_agent(knowledge_path: str = "./knowledge/after_sales"):
    project = create_default_project("复杂企业售后运营 Agent")
    project.project.id = "complex_enterprise_ops_agent"
    project.project.description = "覆盖 JSON 抽取校验、RAG、AI Router、HTTP mock、人审、ForEach/Agent/Merge 与最终回复的复杂 Agent。"
    project.project.template_id = "complex_enterprise_ops_agent"
    project.project.template_version = "1.0.0"
    project.state.fields.extend(
        [
            StateField(name="structured_request", type="dict", description="从用户输入抽取的结构化诉求"),
            StateField(name="request_validation", type="dict", description="结构化诉求校验结果"),
            StateField(name="request_summary", type="str", description="归一化后的用户诉求摘要"),
            StateField(name="order_id", type="str", description="订单号"),
            StateField(name="risk_level", type="str", description="风险等级"),
            StateField(name="task_plan", type="dict", description="批量任务规划"),
            StateField(name="policy_context", type="str", description="RAG 检索到的售后政策上下文"),
            StateField(name="route_key", type="str", description="AI Router 路由结果"),
            StateField(name="route_reason", type="str", description="路由理由"),
            StateField(name="order_info", type="dict", description="订单 API mock 返回"),
            StateField(name="approval_action", type="str", description="人工审批动作"),
            StateField(name="approval_result", type="dict", description="人工审批结果"),
            StateField(name="worker_tasks", type="list", description="拆分后的 Worker 任务"),
            StateField(name="current_task", type="dict", description="ForEach 当前任务"),
            StateField(name="current_task_index", type="int", description="ForEach 当前任务序号"),
            StateField(name="worker_result", type="str", description="单个 Worker 处理结果"),
            StateField(name="worker_results", type="list", description="Worker 结果列表"),
            StateField(name="merge_result", type="dict", description="ForEach Merge 摘要"),
            StateField(name="agent_result", type="str", description="最终 Agent 输出"),
            StateField(name="final_answer", type="str", description="最终回复"),
            StateField(name="last_error", type="dict", description="运行错误"),
            StateField(name="error_result", type="dict", description="错误兜底结果"),
            StateField(name="assignment_result", type="dict", description="变量赋值摘要"),
        ]
    )

    schema_fields = [
        {"name": "intent", "type": "string", "required": True, "enumValues": "order,refund,batch,other", "defaultValue": '"batch"'},
        {"name": "orderId", "type": "string", "description": "订单号", "defaultValue": '"DEMO-ORDER-20260629"'},
        {"name": "riskLevel", "type": "string", "enumValues": "low,medium,high", "defaultValue": '"high"'},
        {
            "name": "tasks",
            "type": "array",
            "itemFields": [
                {"name": "title", "type": "string", "required": True, "defaultValue": '"政策核对"'},
                {"name": "goal", "type": "string", "required": True, "defaultValue": '"核对售后政策并给出建议"'},
            ],
        },
    ]
    task_plan = {
        "tasks": [
            {"id": "policy_check", "title": "政策核对", "goal": "结合 RAG 政策确认是否符合售后规则"},
            {"id": "order_check", "title": "订单核验", "goal": "检查订单状态、物流和退款风险"},
            {"id": "response_plan", "title": "回复策略", "goal": "生成客服回复要点和下一步动作"},
        ]
    }
    project.nodes.extend(
        [
            NodeIR(
                id="extract_request",
                type=NodeType.JSON_EXTRACTOR,
                label="抽取结构化诉求",
                position=Position(x=360, y=120),
                config={
                    "inputText": "{{ state.messages }}",
                    "instruction": "抽取售后请求意图、订单号、风险等级和可拆分任务。",
                    "schemaFieldsJson": json.dumps(schema_fields, ensure_ascii=False),
                    "outputField": "structured_request",
                    "validationField": "request_validation",
                    "repairResultField": "repair_result",
                    "repairEnabled": False,
                },
            ),
            NodeIR(
                id="validate_request",
                type=NodeType.JSON_VALIDATOR,
                label="校验诉求结构",
                position=Position(x=620, y=120),
                config={
                    "inputField": "structured_request",
                    "schemaFieldsJson": json.dumps(schema_fields, ensure_ascii=False),
                    "outputField": "structured_request",
                    "validationField": "request_validation",
                    "repairResultField": "repair_result",
                    "repairEnabled": False,
                },
            ),
            NodeIR(
                id="normalize_request",
                type=NodeType.VARIABLE_ASSIGN,
                label="归一化运行上下文",
                position=Position(x=900, y=120),
                config={
                    "assignmentsJson": json.dumps(
                        [
                            {
                                "target": "request_summary",
                                "operation": "overwrite",
                                "sourceType": "template",
                                "source": "用户诉求：{{ state.messages }}\n结构化请求：{{ state.structured_request }}",
                                "valueType": "string",
                            },
                            {
                                "target": "order_id",
                                "operation": "overwrite",
                                "sourceType": "state",
                                "source": "order_id",
                                "valueType": "string",
                                "transform": "default",
                                "transformArgsJson": json.dumps({"value": "DEMO-ORDER-20260629"}, ensure_ascii=False),
                            },
                            {
                                "target": "risk_level",
                                "operation": "overwrite",
                                "sourceType": "state",
                                "source": "structured_request.riskLevel",
                                "valueType": "string",
                                "transform": "default",
                                "transformArgsJson": json.dumps({"value": "high"}, ensure_ascii=False),
                            },
                            {
                                "target": "task_plan",
                                "operation": "overwrite",
                                "sourceType": "json",
                                "source": json.dumps(task_plan, ensure_ascii=False),
                                "valueType": "json",
                            },
                        ],
                        ensure_ascii=False,
                    ),
                    "resultField": "assignment_result",
                },
            ),
            NodeIR(
                id="retrieve_policy",
                type=NodeType.RETRIEVER,
                label="检索售后政策",
                position=Position(x=1180, y=120),
                config={"source": "local", "path": knowledge_path, "query": "{{ state.request_summary }}", "topK": 4, "outputField": "policy_context"},
            ),
            NodeIR(
                id="route_request",
                type=NodeType.AI_ROUTER,
                label="售后意图路由",
                position=Position(x=1460, y=120),
                config={
                    "routeMode": "keyword",
                    "inputText": "{{ state.messages }}\n{{ state.request_summary }}",
                    "scenarios": "batch:批量处理:批量,多个,并发,拆分,任务\nrefund:退款审批:退款,退货,赔付,取消\norder:订单查询:订单,物流,发货,快递\nother:普通咨询:",
                    "routeField": "route_key",
                    "reasonField": "route_reason",
                    "fallback": "other",
                },
            ),
            NodeIR(
                id="query_order",
                type=NodeType.HTTP,
                label="查询订单 Mock API",
                position=Position(x=1720, y=-80),
                config={
                    "method": "GET",
                    "url": "https://api.example.com/orders/{{ state.order_id }}",
                    "mockEnabled": True,
                    "mockResponseJson": '{"order_id":"{{ state.order_id }}","status":"已发货","tracking_no":"SF202606290001","risk":"{{ state.risk_level }}"}',
                    "outputField": "order_info",
                },
            ),
            NodeIR(
                id="refund_approval",
                type=NodeType.HUMAN_APPROVAL,
                label="高风险退款审批",
                position=Position(x=1720, y=120),
                config={
                    "prompt": "用户申请退款，请结合政策和风险等级审批。\n风险：{{ state.risk_level }}\n政策：{{ state.policy_context }}",
                    "actions": json.dumps(["approved", "rejected", "escalated"], ensure_ascii=False),
                    "defaultAction": "approved",
                    "fallback": "rejected",
                    "actionField": "approval_action",
                    "outputField": "approval_result",
                },
            ),
            NodeIR(
                id="split_tasks",
                type=NodeType.TASK_SPLITTER,
                label="拆分批量任务",
                position=Position(x=1720, y=320),
                config={"inputField": "task_plan", "outputField": "worker_tasks", "maxTasks": 5, "fallbackToSingleTask": True},
            ),
            NodeIR(
                id="iterate_tasks",
                type=NodeType.FOR_EACH,
                label="并行处理子任务",
                position=Position(x=1980, y=320),
                config={
                    "itemsField": "worker_tasks",
                    "itemField": "current_task",
                    "indexField": "current_task_index",
                    "executionMode": "parallel",
                    "maxConcurrency": 3,
                    "maxItems": 10,
                    "preserveOrder": True,
                    "itemFailurePolicy": "collect_errors",
                    "resultField": "for_each_result",
                },
            ),
            NodeIR(
                id="task_worker",
                type=NodeType.AGENT,
                label="运营 Worker Agent",
                position=Position(x=2240, y=320),
                config={
                    "systemPrompt": "你是售后运营 Worker，负责处理单个子任务并输出简洁结论。",
                    "userPrompt": "当前子任务：{{ state.current_task }}\n政策上下文：{{ state.policy_context }}\n订单信息：{{ state.order_info }}",
                    "outputField": "worker_result",
                    "maxIterations": 2,
                },
            ),
            NodeIR(
                id="merge_task_results",
                type=NodeType.MERGE,
                label="汇总 Worker 结果",
                position=Position(x=2500, y=320),
                config={
                    "mergeMode": "for_each",
                    "reducersJson": json.dumps([{"target": "worker_results", "source": "worker_result", "reducer": "append"}], ensure_ascii=False),
                    "resultField": "merge_result",
                },
            ),
            NodeIR(
                id="final_agent",
                type=NodeType.AGENT,
                label="最终客服策略 Agent",
                position=Position(x=2780, y=120),
                config={
                    "systemPrompt": "你是企业售后运营 Agent，结合路由、政策、订单、人审和 Worker 结果生成最终回复。",
                    "userPrompt": "用户：{{ state.messages }}\n路由：{{ state.route_key }}\n政策：{{ state.policy_context }}\n订单：{{ state.order_info }}\n审批：{{ state.approval_result }}\n批量结果：{{ state.worker_results }}",
                    "outputField": "agent_result",
                    "maxIterations": 2,
                },
            ),
            NodeIR(
                id="handle_invalid",
                type=NodeType.ERROR_HANDLER,
                label="结构化失败兜底",
                position=Position(x=900, y=420),
                config={
                    "errorField": "last_error",
                    "template": "结构化请求未通过校验，请补充订单号、诉求类型或任务列表。错误：{{ state.request_validation }}",
                    "outputField": "error_result",
                },
            ),
            NodeIR(
                id="reply_final",
                type=NodeType.DIRECT_REPLY,
                label="回复用户",
                position=Position(x=3060, y=120),
                config={"template": "{{ state.agent_result }}{{ state.error_result }}", "outputField": "final_answer"},
            ),
        ]
    )
    project.edges.extend(
        [
            EdgeIR(id="edge_start_extract", source="start", target="extract_request"),
            EdgeIR(id="edge_extract_valid", source="extract_request", sourceHandle="valid", target="validate_request", kind=EdgeKind.CONDITIONAL),
            EdgeIR(id="edge_extract_invalid", source="extract_request", sourceHandle="invalid", target="handle_invalid", kind=EdgeKind.CONDITIONAL),
            EdgeIR(id="edge_validate_valid", source="validate_request", sourceHandle="valid", target="normalize_request", kind=EdgeKind.CONDITIONAL),
            EdgeIR(id="edge_validate_invalid", source="validate_request", sourceHandle="invalid", target="handle_invalid", kind=EdgeKind.CONDITIONAL),
            EdgeIR(id="edge_normalize_retrieve", source="normalize_request", target="retrieve_policy"),
            EdgeIR(id="edge_retrieve_route", source="retrieve_policy", target="route_request"),
            EdgeIR(id="edge_route_order", source="route_request", sourceHandle="order", target="query_order", kind=EdgeKind.CONDITIONAL),
            EdgeIR(id="edge_route_refund", source="route_request", sourceHandle="refund", target="refund_approval", kind=EdgeKind.CONDITIONAL),
            EdgeIR(id="edge_route_batch", source="route_request", sourceHandle="batch", target="split_tasks", kind=EdgeKind.CONDITIONAL),
            EdgeIR(id="edge_route_other", source="route_request", sourceHandle="other", target="final_agent", kind=EdgeKind.CONDITIONAL),
            EdgeIR(id="edge_order_final", source="query_order", target="final_agent"),
            EdgeIR(id="edge_refund_approved", source="refund_approval", sourceHandle="approved", target="final_agent", kind=EdgeKind.CONDITIONAL),
            EdgeIR(id="edge_refund_rejected", source="refund_approval", sourceHandle="rejected", target="final_agent", kind=EdgeKind.CONDITIONAL),
            EdgeIR(id="edge_refund_escalated", source="refund_approval", sourceHandle="escalated", target="final_agent", kind=EdgeKind.CONDITIONAL),
            EdgeIR(id="edge_split_iterate", source="split_tasks", target="iterate_tasks"),
            EdgeIR(id="edge_iterate_worker", source="iterate_tasks", sourceHandle="item", target="task_worker"),
            EdgeIR(id="edge_worker_merge", source="task_worker", target="merge_task_results"),
            EdgeIR(id="edge_merge_final", source="merge_task_results", target="final_agent"),
            EdgeIR(id="edge_error_reply", source="handle_invalid", target="reply_final"),
            EdgeIR(id="edge_final_reply", source="final_agent", target="reply_final"),
        ]
    )
    return project
