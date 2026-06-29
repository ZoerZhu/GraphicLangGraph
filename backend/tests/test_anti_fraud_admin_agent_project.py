from app.ir.schemas import EdgeIR, EdgeKind, NodeIR, NodeType, Position, StateField, create_default_project
from app.ir.validation import validate_project
from app.runner import preview

import json


def test_anti_fraud_admin_agent_validates_and_dry_runs_read_path():
    project = build_anti_fraud_admin_agent()

    validation = validate_project(project)
    assert validation.valid, [issue.model_dump() for issue in validation.issues]

    trace, state = preview.run_project_preview(project, {"messages": "查看后台看板统计概览"}, "dry")

    assert [item["nodeId"] for item in trace] == [
        "init_admin_context",
        "login_admin",
        "route_admin_task",
        "get_dashboard",
        "summarize_admin_result",
        "reply_admin_result",
    ]
    assert state["route_key"] == "dashboard"
    assert state["management_result"]["status"] == "dry-run"
    assert "/api/statistics/dashboard" in state["management_result"]["url"]
    assert state["admin_analysis"].startswith("[dry-run]")
    assert state["final_answer"]


def test_anti_fraud_admin_agent_dry_run_write_path_requires_approval_before_http():
    project = build_anti_fraud_admin_agent()

    trace, state = preview.run_project_preview(project, {"messages": "禁用用户 1", "target_id": 1}, "dry")

    trace_ids = [item["nodeId"] for item in trace]
    assert trace_ids == [
        "init_admin_context",
        "login_admin",
        "route_admin_task",
        "approve_disable_user",
        "summarize_admin_result",
        "reply_admin_result",
    ]
    assert state["route_key"] == "disable_user"
    assert state["approval_action"] == "rejected"
    assert "management_result" not in state
    assert "disable_user" not in trace_ids


def test_http_node_renders_dynamic_headers(monkeypatch):
    from app.ir.schemas import EdgeIR, NodeIR, NodeType
    from app.runner.nodes import http

    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": True}

    def fake_request(method, url, headers=None, content=None, timeout=None):
        captured.update({"method": method, "url": url, "headers": headers, "content": content, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setattr(http.httpx, "request", fake_request)

    project = create_default_project("Dynamic Headers")
    project.state.fields.extend([StateField(name="token", type="str"), StateField(name="http_response", type="dict"), StateField(name="final_answer", type="str")])
    project.nodes.extend(
        [
            NodeIR(
                id="http_call",
                type=NodeType.HTTP,
                label="HTTP",
                config={
                    "method": "GET",
                    "url": "http://localhost:8080/api/user/list",
                    "headersJson": '{"Authorization":"Bearer {{ state.token }}","X-Trace":"{{ state.trace_id }}"}',
                    "outputField": "http_response",
                },
            ),
            NodeIR(id="reply", type=NodeType.DIRECT_REPLY, label="Reply", config={"template": "{{ state.http_response }}", "outputField": "final_answer"}),
        ]
    )
    project.edges.extend([EdgeIR(id="e1", source="start", target="http_call"), EdgeIR(id="e2", source="http_call", target="reply")])

    _trace, state = preview.run_project_preview(project, {"token": "abc123", "trace_id": "run-1"}, "live")

    assert state["http_response"] == {"ok": True}
    assert captured["headers"] == {"Authorization": "Bearer abc123", "X-Trace": "run-1"}


def build_anti_fraud_admin_agent(base_url: str = "http://localhost:8080"):
    project = create_default_project("反诈平台管理员 Agent")
    project.project.id = "anti_fraud_admin_agent"
    project.project.description = (
        "连接本地 4547springboot 反诈骗学习平台，支持用户、案例、资讯、关卡和统计数据的管理员查询；"
        "高风险写操作必须先经过 Human Approval。"
    )
    project.state.fields.extend(
        [
            StateField(name="api_base_url", type="str", description="Spring Boot API base URL"),
            StateField(name="admin_username", type="str", description="管理员用户名，运行时输入"),
            StateField(name="admin_password", type="str", description="管理员密码，运行时输入"),
            StateField(name="login_result", type="dict", description="登录接口返回，包含 data.token"),
            StateField(name="page_num", type="int", description="分页页码"),
            StateField(name="page_size", type="int", description="分页大小"),
            StateField(name="target_id", type="int", description="写操作目标 ID，例如用户 ID、资讯 ID、案例 ID"),
            StateField(name="featured_flag", type="int", description="案例精选标记，1 精选，0 取消"),
            StateField(name="route_key", type="str", description="管理员任务路由"),
            StateField(name="route_reason", type="str", description="路由原因"),
            StateField(name="approval_action", type="str", description="写操作审批动作"),
            StateField(name="approval_result", type="dict", description="写操作审批结果"),
            StateField(name="management_result", type="dict", description="管理接口返回"),
            StateField(name="admin_analysis", type="str", description="LLM 生成的管理结果归纳"),
            StateField(name="assignment_result", type="dict", description="上下文初始化结果"),
            StateField(name="final_answer", type="str", description="最终回复"),
        ]
    )
    project.nodes.extend(
        [
            NodeIR(
                id="init_admin_context",
                type=NodeType.VARIABLE_ASSIGN,
                label="初始化管理员参数",
                position=Position(x=360, y=180),
                config={
                    "assignmentsJson": json.dumps(
                        [
                            {
                                "target": "api_base_url",
                                "operation": "overwrite",
                                "sourceType": "state",
                                "source": "api_base_url",
                                "valueType": "string",
                                "transform": "default",
                                "transformArgsJson": json.dumps({"value": base_url}, ensure_ascii=False),
                            },
                            {
                                "target": "admin_username",
                                "operation": "overwrite",
                                "sourceType": "state",
                                "source": "admin_username",
                                "valueType": "string",
                                "transform": "default",
                                "transformArgsJson": json.dumps({"value": "admin"}, ensure_ascii=False),
                            },
                            {
                                "target": "admin_password",
                                "operation": "overwrite",
                                "sourceType": "state",
                                "source": "admin_password",
                                "valueType": "string",
                                "transform": "default",
                                "transformArgsJson": json.dumps({"value": ""}, ensure_ascii=False),
                            },
                            {
                                "target": "page_num",
                                "operation": "overwrite",
                                "sourceType": "state",
                                "source": "page_num",
                                "valueType": "integer",
                                "transform": "default",
                                "transformArgsJson": json.dumps({"value": 1}, ensure_ascii=False),
                            },
                            {
                                "target": "page_size",
                                "operation": "overwrite",
                                "sourceType": "state",
                                "source": "page_size",
                                "valueType": "integer",
                                "transform": "default",
                                "transformArgsJson": json.dumps({"value": 10}, ensure_ascii=False),
                            },
                            {
                                "target": "target_id",
                                "operation": "overwrite",
                                "sourceType": "state",
                                "source": "target_id",
                                "valueType": "integer",
                                "transform": "default",
                                "transformArgsJson": json.dumps({"value": 1}, ensure_ascii=False),
                            },
                            {
                                "target": "featured_flag",
                                "operation": "overwrite",
                                "sourceType": "state",
                                "source": "featured_flag",
                                "valueType": "integer",
                                "transform": "default",
                                "transformArgsJson": json.dumps({"value": 1}, ensure_ascii=False),
                            },
                        ],
                        ensure_ascii=False,
                    ),
                    "resultField": "assignment_result",
                },
            ),
            NodeIR(
                id="login_admin",
                type=NodeType.HTTP,
                label="登录管理员账号",
                position=Position(x=640, y=-20),
                config={
                    "method": "POST",
                    "url": "{{ state.api_base_url }}/api/user/login",
                    "headersJson": '{"Content-Type":"application/json"}',
                    "body": '{"username":"{{ state.admin_username }}","password":"{{ state.admin_password }}"}',
                    "timeoutSeconds": 15,
                    "outputField": "login_result",
                },
            ),
            NodeIR(
                id="route_admin_task",
                type=NodeType.AI_ROUTER,
                label="识别管理员任务",
                position=Position(x=640, y=180),
                config={
                    "routeMode": "llm",
                    "provider": "openai",
                    "model": "gpt-4.1-mini",
                    "instruction": (
                        "你是后台管理员任务路由器。请根据用户请求选择最合适的 route key；"
                        "如果模型不可用，运行时会回退到关键词路由。"
                    ),
                    "inputText": "{{ state.messages }}",
                    "scenarios": "\n".join(
                        [
                            "disable_user:禁用用户:禁用,封禁,停用",
                            "enable_user:启用用户:启用,恢复用户,解除禁用",
                            "refresh_stats:刷新统计:刷新统计,重算统计,统计刷新",
                            "publish_news:发布资讯:发布资讯,发布新闻,上线资讯",
                            "feature_case:精选案例:精选案例,设置精选,取消精选",
                            "dashboard:后台看板:看板,概览,统计,dashboard",
                            "users:用户管理:用户,账号,学生,成员",
                            "cases:案例管理:案例,诈骗案例,case",
                            "news:资讯管理:资讯,新闻,公告,预警,news",
                            "challenges:关卡管理:闯关,关卡,挑战,challenge",
                            "other:兜底咨询:",
                        ]
                    ),
                    "routeField": "route_key",
                    "reasonField": "route_reason",
                    "fallback": "other",
                },
            ),
            http_node("get_dashboard", "读取后台看板", 940, -180, "GET", "{{ state.api_base_url }}/api/statistics/dashboard"),
            http_node("list_users", "查询用户列表", 940, -20, "GET", "{{ state.api_base_url }}/api/user/list?pageNum={{ state.page_num }}&pageSize={{ state.page_size }}"),
            http_node("list_cases", "查询案例列表", 940, 140, "GET", "{{ state.api_base_url }}/api/case/page?pageNum={{ state.page_num }}&pageSize={{ state.page_size }}"),
            http_node("list_news", "查询资讯列表", 940, 300, "GET", "{{ state.api_base_url }}/api/news/page?pageNum={{ state.page_num }}&pageSize={{ state.page_size }}"),
            http_node("list_challenges", "查询关卡列表", 940, 460, "GET", "{{ state.api_base_url }}/api/challenge/admin/list?pageNum={{ state.page_num }}&pageSize={{ state.page_size }}"),
            approval_node("approve_disable_user", "审批禁用用户", 1240, -20, "确认禁用用户 {{ state.target_id }}？"),
            approval_node("approve_enable_user", "审批启用用户", 1240, 120, "确认启用用户 {{ state.target_id }}？"),
            approval_node("approve_refresh_stats", "审批刷新统计", 1240, 260, "确认手动刷新统计数据？"),
            approval_node("approve_publish_news", "审批发布资讯", 1240, 400, "确认发布资讯 {{ state.target_id }}？"),
            approval_node("approve_feature_case", "审批精选案例", 1240, 540, "确认设置案例 {{ state.target_id }} 的精选状态为 {{ state.featured_flag }}？"),
            http_node("disable_user", "执行禁用用户", 1540, -20, "PUT", "{{ state.api_base_url }}/api/user/{{ state.target_id }}/disable"),
            http_node("enable_user", "执行启用用户", 1540, 120, "PUT", "{{ state.api_base_url }}/api/user/{{ state.target_id }}/enable"),
            http_node("refresh_stats", "执行刷新统计", 1540, 260, "POST", "{{ state.api_base_url }}/api/statistics/refresh"),
            http_node("publish_news", "执行发布资讯", 1540, 400, "POST", "{{ state.api_base_url }}/api/news/{{ state.target_id }}/publish"),
            http_node("feature_case", "执行精选案例", 1540, 540, "PUT", "{{ state.api_base_url }}/api/case/{{ state.target_id }}/featured?isFeatured={{ state.featured_flag }}"),
            NodeIR(
                id="explain_other",
                type=NodeType.TEMPLATE,
                label="解释可用管理能力",
                position=Position(x=940, y=640),
                config={
                    "template": "我可以管理本地反诈平台数据：查看看板、用户列表、案例列表、资讯列表、关卡列表；禁用/启用用户、发布资讯、设置案例精选、刷新统计需要审批。",
                    "outputType": "text",
                    "outputField": "management_result",
                },
            ),
            NodeIR(
                id="summarize_admin_result",
                type=NodeType.LLM,
                label="生成管理分析",
                position=Position(x=1840, y=180),
                config={
                    "provider": "openai",
                    "model": "gpt-4.1-mini",
                    "systemPrompt": (
                        "你是反诈骗学习平台的后台管理员助手。"
                        "请基于真实接口结果和审批状态，用中文给出简洁、可执行的管理结论。"
                        "不要编造接口中没有的数据；涉及写操作时说明是否已审批、是否已执行。"
                    ),
                    "userPrompt": (
                        "用户请求：{{ state.messages }}\n"
                        "路由：{{ state.route_key }}\n"
                        "路由原因：{{ state.route_reason }}\n"
                        "审批结果：{{ state.approval_result }}\n"
                        "接口/兜底结果：{{ state.management_result }}\n"
                        "请输出：1. 本次任务结果；2. 关键数据摘要；3. 风险或下一步建议。"
                    ),
                    "outputField": "admin_analysis",
                    "errorPolicy": "fallback",
                    "fallbackOutputJson": json.dumps(
                        {
                            "admin_analysis": (
                                "LLM 分析暂不可用，已返回原始管理结果。"
                                "请检查模型配置后重试；当前任务={{ state.route_key }}，接口结果={{ state.management_result }}，审批={{ state.approval_result }}。"
                            )
                        },
                        ensure_ascii=False,
                    ),
                },
            ),
            NodeIR(
                id="reply_admin_result",
                type=NodeType.DIRECT_REPLY,
                label="返回管理结果",
                position=Position(x=2140, y=180),
                config={
                    "template": "管理员任务：{{ state.route_key }}\n\n管理分析：{{ state.admin_analysis }}\n\n审批：{{ state.approval_result }}\n接口结果：{{ state.management_result }}",
                    "outputField": "final_answer",
                },
            ),
        ]
    )
    project.edges.extend(
        [
            EdgeIR(id="e_start_init", source="start", target="init_admin_context"),
            EdgeIR(id="e_init_login", source="init_admin_context", target="login_admin"),
            EdgeIR(id="e_login_route", source="login_admin", target="route_admin_task"),
            EdgeIR(id="e_route_dashboard", source="route_admin_task", sourceHandle="dashboard", target="get_dashboard", kind=EdgeKind.CONDITIONAL),
            EdgeIR(id="e_route_users", source="route_admin_task", sourceHandle="users", target="list_users", kind=EdgeKind.CONDITIONAL),
            EdgeIR(id="e_route_cases", source="route_admin_task", sourceHandle="cases", target="list_cases", kind=EdgeKind.CONDITIONAL),
            EdgeIR(id="e_route_news", source="route_admin_task", sourceHandle="news", target="list_news", kind=EdgeKind.CONDITIONAL),
            EdgeIR(id="e_route_challenges", source="route_admin_task", sourceHandle="challenges", target="list_challenges", kind=EdgeKind.CONDITIONAL),
            EdgeIR(id="e_route_disable", source="route_admin_task", sourceHandle="disable_user", target="approve_disable_user", kind=EdgeKind.CONDITIONAL),
            EdgeIR(id="e_route_enable", source="route_admin_task", sourceHandle="enable_user", target="approve_enable_user", kind=EdgeKind.CONDITIONAL),
            EdgeIR(id="e_route_refresh", source="route_admin_task", sourceHandle="refresh_stats", target="approve_refresh_stats", kind=EdgeKind.CONDITIONAL),
            EdgeIR(id="e_route_publish", source="route_admin_task", sourceHandle="publish_news", target="approve_publish_news", kind=EdgeKind.CONDITIONAL),
            EdgeIR(id="e_route_feature", source="route_admin_task", sourceHandle="feature_case", target="approve_feature_case", kind=EdgeKind.CONDITIONAL),
            EdgeIR(id="e_route_other", source="route_admin_task", sourceHandle="other", target="explain_other", kind=EdgeKind.CONDITIONAL),
            EdgeIR(id="e_dashboard_summarize", source="get_dashboard", target="summarize_admin_result"),
            EdgeIR(id="e_users_summarize", source="list_users", target="summarize_admin_result"),
            EdgeIR(id="e_cases_summarize", source="list_cases", target="summarize_admin_result"),
            EdgeIR(id="e_news_summarize", source="list_news", target="summarize_admin_result"),
            EdgeIR(id="e_challenges_summarize", source="list_challenges", target="summarize_admin_result"),
            EdgeIR(id="e_other_summarize", source="explain_other", target="summarize_admin_result"),
            EdgeIR(id="e_disable_approved", source="approve_disable_user", sourceHandle="approved", target="disable_user", kind=EdgeKind.CONDITIONAL),
            EdgeIR(id="e_disable_rejected", source="approve_disable_user", sourceHandle="rejected", target="summarize_admin_result", kind=EdgeKind.CONDITIONAL),
            EdgeIR(id="e_enable_approved", source="approve_enable_user", sourceHandle="approved", target="enable_user", kind=EdgeKind.CONDITIONAL),
            EdgeIR(id="e_enable_rejected", source="approve_enable_user", sourceHandle="rejected", target="summarize_admin_result", kind=EdgeKind.CONDITIONAL),
            EdgeIR(id="e_refresh_approved", source="approve_refresh_stats", sourceHandle="approved", target="refresh_stats", kind=EdgeKind.CONDITIONAL),
            EdgeIR(id="e_refresh_rejected", source="approve_refresh_stats", sourceHandle="rejected", target="summarize_admin_result", kind=EdgeKind.CONDITIONAL),
            EdgeIR(id="e_publish_approved", source="approve_publish_news", sourceHandle="approved", target="publish_news", kind=EdgeKind.CONDITIONAL),
            EdgeIR(id="e_publish_rejected", source="approve_publish_news", sourceHandle="rejected", target="summarize_admin_result", kind=EdgeKind.CONDITIONAL),
            EdgeIR(id="e_feature_approved", source="approve_feature_case", sourceHandle="approved", target="feature_case", kind=EdgeKind.CONDITIONAL),
            EdgeIR(id="e_feature_rejected", source="approve_feature_case", sourceHandle="rejected", target="summarize_admin_result", kind=EdgeKind.CONDITIONAL),
            EdgeIR(id="e_disable_summarize", source="disable_user", target="summarize_admin_result"),
            EdgeIR(id="e_enable_summarize", source="enable_user", target="summarize_admin_result"),
            EdgeIR(id="e_refresh_summarize", source="refresh_stats", target="summarize_admin_result"),
            EdgeIR(id="e_publish_summarize", source="publish_news", target="summarize_admin_result"),
            EdgeIR(id="e_feature_summarize", source="feature_case", target="summarize_admin_result"),
            EdgeIR(id="e_summarize_reply", source="summarize_admin_result", target="reply_admin_result"),
        ]
    )
    return project


def http_node(node_id: str, label: str, x: int, y: int, method: str, url: str) -> NodeIR:
    return NodeIR(
        id=node_id,
        type=NodeType.HTTP,
        label=label,
        position=Position(x=x, y=y),
        config={
            "method": method,
            "url": url,
            "headersJson": '{"Authorization":"Bearer {{ state.login_result.data.token }}"}',
            "timeoutSeconds": 15,
            "outputField": "management_result",
        },
    )


def approval_node(node_id: str, label: str, x: int, y: int, prompt: str) -> NodeIR:
    return NodeIR(
        id=node_id,
        type=NodeType.HUMAN_APPROVAL,
        label=label,
        position=Position(x=x, y=y),
        config={
            "prompt": prompt,
            "actions": json.dumps(["approved", "rejected"], ensure_ascii=False),
            "defaultAction": "rejected",
            "fallback": "rejected",
            "actionField": "approval_action",
            "outputField": "approval_result",
        },
    )
