import json
import sys
from types import SimpleNamespace
from pathlib import Path

from app.ir.schemas import EdgeIR, EdgeKind, NodeIR, NodeType, SkillConfig, StateField, ToolConfig, create_default_project
from app.runner import preview


class FakeResponse:
    def __init__(self, content: str) -> None:
        self.content = content


def test_live_preview_runs_knowledge_qa_chain(monkeypatch, tmp_path: Path):
    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()
    (knowledge_dir / "refund.md").write_text("退款政策：订单签收后 7 天内可以申请退款。", encoding="utf-8")

    def fake_call_chat_model(provider, model, messages, runtime_config=None):
        system = messages[0][1] if messages and messages[0][0] == "system" else ""
        if "问题改写" in system:
            return FakeResponse("退款政策")
        return FakeResponse("根据知识库，订单签收后 7 天内可以申请退款。")

    monkeypatch.setattr(preview, "_call_chat_model", fake_call_chat_model)

    project = create_default_project("知识库问答")
    project.state.fields.extend(
        [
            StateField(name="rewritten_query", type="str"),
            StateField(name="retrieved_context", type="str"),
            StateField(name="final_answer", type="str"),
        ]
    )
    project.nodes.extend(
        [
            NodeIR(
                id="llm_rewrite",
                type=NodeType.LLM,
                label="改写问题",
                config={
                    "systemPrompt": "你是问题改写器。",
                    "userPrompt": "{{ state.messages }}",
                    "outputField": "rewritten_query",
                },
            ),
            NodeIR(
                id="retriever_context",
                type=NodeType.RETRIEVER,
                label="检索知识库",
                config={
                    "path": str(knowledge_dir),
                    "query": "{{ state.rewritten_query }}",
                    "topK": 2,
                    "outputField": "retrieved_context",
                },
            ),
            NodeIR(
                id="llm_answer",
                type=NodeType.LLM,
                label="生成回答",
                config={
                    "systemPrompt": "你是问答助手。",
                    "userPrompt": "上下文：{{ state.retrieved_context }}",
                    "outputField": "final_answer",
                },
            ),
            NodeIR(
                id="reply_final",
                type=NodeType.DIRECT_REPLY,
                label="回复",
                config={"template": "{{ state.final_answer }}", "outputField": "final_answer"},
            ),
        ]
    )
    project.edges.extend(
        [
            EdgeIR(id="e1", source="start", target="llm_rewrite"),
            EdgeIR(id="e2", source="llm_rewrite", target="retriever_context"),
            EdgeIR(id="e3", source="retriever_context", target="llm_answer"),
            EdgeIR(id="e4", source="llm_answer", target="reply_final"),
        ]
    )

    trace, state = preview.run_project_preview(project, {"messages": "我可以退款吗？"}, "live")

    assert [item["nodeId"] for item in trace] == ["llm_rewrite", "retriever_context", "llm_answer", "reply_final"]
    assert {item["status"] for item in trace} == {"ok"}
    assert "refund.md" in state["retrieved_context"]
    assert state["final_answer"] == "根据知识库，订单签收后 7 天内可以申请退款。"


def test_live_preview_uses_runtime_model_config(monkeypatch):
    seen = {}

    def fake_call_chat_model(provider, model, messages, runtime_config=None):
        seen["provider"] = provider
        seen["model"] = model
        seen["runtime_config"] = runtime_config
        return FakeResponse("使用运行配置生成的回答")

    monkeypatch.setattr(preview, "_call_chat_model", fake_call_chat_model)

    project = create_default_project("模型配置运行测试")
    project.nodes.extend(
        [
            NodeIR(
                id="llm_answer",
                type=NodeType.LLM,
                label="生成回答",
                config={
                    "provider": "openai",
                    "model": "gpt-4.1-mini",
                    "userPrompt": "{{ state.messages }}",
                    "outputField": "final_answer",
                },
            ),
            NodeIR(
                id="reply_final",
                type=NodeType.DIRECT_REPLY,
                label="回复",
                config={"template": "{{ state.final_answer }}", "outputField": "final_answer"},
            ),
        ]
    )
    project.edges.extend(
        [
            EdgeIR(id="e1", source="start", target="llm_answer"),
            EdgeIR(id="e2", source="llm_answer", target="reply_final"),
        ]
    )

    trace, state = preview.run_project_preview(
        project,
        {"messages": "你好"},
        "live",
        {
            "name": "DeepSeek 测试",
            "provider": "deepseek",
            "model": "deepseek-chat",
            "baseUrl": "https://api.deepseek.com",
            "apiKeyEnv": "DEEPSEEK_API_KEY",
            "enabled": True,
        },
    )

    assert {item["status"] for item in trace} == {"ok"}
    assert seen["provider"] == "deepseek"
    assert seen["model"] == "deepseek-chat"
    assert seen["runtime_config"]["baseUrl"] == "https://api.deepseek.com"
    assert state["final_answer"] == "使用运行配置生成的回答"


def test_live_preview_keeps_explicit_node_model(monkeypatch):
    seen = {}

    def fake_call_chat_model(provider, model, messages, runtime_config=None):
        seen["provider"] = provider
        seen["model"] = model
        seen["runtime_config"] = runtime_config
        return FakeResponse("使用节点模型生成的回答")

    monkeypatch.setattr(preview, "_call_chat_model", fake_call_chat_model)

    project = create_default_project("节点模型优先测试")
    project.nodes.extend(
        [
            NodeIR(
                id="llm_answer",
                type=NodeType.LLM,
                label="生成回答",
                config={
                    "provider": "mimo",
                    "model": "mimo-v2.5-pro",
                    "modelConfigId": "model_mimo",
                    "userPrompt": "{{ state.messages }}",
                    "outputField": "final_answer",
                },
            ),
            NodeIR(
                id="reply_final",
                type=NodeType.DIRECT_REPLY,
                label="回复",
                config={"template": "{{ state.final_answer }}", "outputField": "final_answer"},
            ),
        ]
    )
    project.edges.extend(
        [
            EdgeIR(id="e1", source="start", target="llm_answer"),
            EdgeIR(id="e2", source="llm_answer", target="reply_final"),
        ]
    )

    trace, state = preview.run_project_preview(
        project,
        {"messages": "你好"},
        "live",
        {
            "name": "运行面板模型",
            "provider": "mimo",
            "model": "gpt-4.1-mini",
            "baseUrl": "https://token-plan-cn.xiaomimimo.com/v1",
            "enabled": True,
        },
    )

    assert {item["status"] for item in trace} == {"ok"}
    assert seen["provider"] == "mimo"
    assert seen["model"] == "mimo-v2.5-pro"
    assert seen["runtime_config"]["baseUrl"] == "https://token-plan-cn.xiaomimimo.com/v1"
    assert state["final_answer"] == "使用节点模型生成的回答"


def test_live_preview_injects_selected_skills_into_agent_system_prompt(monkeypatch):
    seen = {}

    def fake_call_chat_model(provider, model, messages, runtime_config=None):
        seen["messages"] = messages
        return FakeResponse("已按 Skill 输出")

    monkeypatch.setattr(preview, "_call_chat_model", fake_call_chat_model)

    project = create_default_project("Skill 注入测试")
    project.skills.append(
        SkillConfig(
            id="skill_tone",
            name="语气控制",
            description="控制客服语气",
            content="请保持礼貌、简洁，并给出可执行下一步。",
        )
    )
    project.nodes.append(
        NodeIR(
            id="support_agent",
            type=NodeType.AGENT,
            label="客服 Agent",
            config={
                "systemPrompt": "你是客服助手。",
                "skillIdsJson": '["skill_tone"]',
                "outputField": "agent_result",
            },
        )
    )
    project.edges.append(EdgeIR(id="e1", source="start", target="support_agent"))

    trace, state = preview.run_project_preview(project, {"messages": "怎么退款？"}, "live")

    assert trace[0]["status"] == "ok"
    assert state["agent_result"] == "已按 Skill 输出"
    assert seen["messages"][0][0] == "system"
    assert "可用 Skills:" in seen["messages"][0][1]
    assert "### 语气控制" in seen["messages"][0][1]
    assert "请保持礼貌" in seen["messages"][0][1]


def test_live_preview_skill_node_writes_skill_content():
    project = create_default_project("Skill Node 测试")
    project.skills.append(
        SkillConfig(
            id="skill_context",
            name="业务说明",
            content="订单状态字段说明。",
        )
    )
    project.nodes.append(
        NodeIR(
            id="skill_context_node",
            type=NodeType.SKILL_NODE,
            label="业务说明",
            config={"skillId": "skill_context", "skillName": "业务说明", "outputField": "skill_context"},
        )
    )
    project.edges.append(EdgeIR(id="e1", source="start", target="skill_context_node"))

    trace, state = preview.run_project_preview(project, {"messages": "查询订单"}, "live")

    assert trace[0]["status"] == "ok"
    assert state["skill_context"] == "订单状态字段说明。"


def test_live_preview_tools_node_can_call_registered_tool_multiple_times(monkeypatch, tmp_path: Path):
    tool_file = tmp_path / "local_tools.py"
    tool_file.write_text(
        """
def echo(query: str, suffix: str = "") -> str:
    return f"{query}{suffix}"
""",
        encoding="utf-8",
    )
    schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "suffix": {"type": "string"},
        },
        "required": ["query"],
        "x-graphic": {
            "kind": "python_function",
            "sourcePath": str(tool_file),
            "function": "echo",
        },
    }
    seen_messages = []

    def fake_call_chat_model(provider, model, messages, runtime_config=None):
        seen_messages.append(messages)
        if len(seen_messages) == 1:
            return FakeResponse(
                json.dumps(
                    {
                        "tool_calls": [
                            {"tool": "echo", "args": {"query": "A"}},
                            {"tool": "echo", "args": {"query": "B", "suffix": "!"}},
                        ],
                        "final_answer": "",
                    }
                )
            )
        return FakeResponse(json.dumps({"tool_calls": [], "final_answer": "工具调用完成"}))

    monkeypatch.setattr(preview, "_call_chat_model", fake_call_chat_model)

    project = create_default_project("Tools Agent 测试")
    project.state.fields.extend(
        [
            StateField(name="tools_result", type="str"),
            StateField(name="tools_result_tool_calls", type="list"),
        ]
    )
    project.tools.append(
        ToolConfig(
            id="tool_echo",
            name="echo",
            description="Echo test tool",
            source="python",
            schemaJson=json.dumps(schema),
        )
    )
    project.nodes.append(
        NodeIR(
            id="tools_agent",
            type=NodeType.TOOL,
            label="Tools",
            config={
                "provider": "openai",
                "model": "gpt-4.1-mini",
                "systemPrompt": "选择合适工具。",
                "toolIdsJson": '["tool_echo"]',
                "maxIterations": 3,
                "outputField": "tools_result",
            },
        )
    )
    project.edges.append(EdgeIR(id="e1", source="start", target="tools_agent"))

    trace, state = preview.run_project_preview(project, {"messages": "调用 echo 两次"}, "live")

    assert trace[0]["status"] == "ok"
    assert state["tools_result"] == "工具调用完成"
    assert len(state["tools_result_tool_calls"]) == 2
    assert state["tools_result_tool_calls"][0]["observation"]["result"] == "A"
    assert state["tools_result_tool_calls"][1]["observation"]["result"] == "B!"
    assert "可用工具" in seen_messages[0][0][1]
    assert "工具执行结果" in seen_messages[1][-1][1]


def test_openai_compatible_base_url_can_run_without_configured_key(monkeypatch):
    seen = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            seen["kwargs"] = kwargs

        def invoke(self, messages):
            seen["messages"] = messages
            return FakeResponse("无密钥代理响应")

    monkeypatch.setitem(sys.modules, "langchain_openai", SimpleNamespace(ChatOpenAI=FakeChatOpenAI))

    response = preview._call_chat_model(
        "mimo",
        "mimo-v2.5-pro",
        [("user", "你好")],
        {"baseUrl": "https://token-plan-cn.xiaomimimo.com/v1"},
    )

    assert response.content == "无密钥代理响应"
    assert seen["kwargs"]["base_url"] == "https://token-plan-cn.xiaomimimo.com/v1"
    assert seen["kwargs"]["api_key"] == "not-needed"


def test_openai_compatible_ignores_invalid_api_key_env(monkeypatch):
    seen = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            seen["kwargs"] = kwargs

        def invoke(self, messages):
            return FakeResponse("忽略非法环境变量名")

    monkeypatch.setitem(sys.modules, "langchain_openai", SimpleNamespace(ChatOpenAI=FakeChatOpenAI))

    response = preview._call_chat_model(
        "mimo",
        "mimo-v2.5-pro",
        [("user", "你好")],
        {
            "baseUrl": "https://token-plan-cn.xiaomimimo.com/v1",
            "apiKeyEnv": "tp-not-an-env-name",
        },
    )

    assert response.content == "忽略非法环境变量名"
    assert seen["kwargs"]["api_key"] == "not-needed"


def test_live_preview_runs_chroma_retriever_with_sidecar_embedding(monkeypatch, tmp_path: Path):
    chroma_dir = tmp_path / "data" / "chroma"
    chroma_dir.mkdir(parents=True)
    (chroma_dir / "chroma.sqlite3").write_text("", encoding="utf-8")
    (chroma_dir.parent / "runtime_config.json").write_text(
        json.dumps(
            {
                "COLLECTION_NAME": "national_formulary_v2",
                "EMBEDDING_MODEL": "text-embedding-v4",
                "EMBEDDING_API_BASE": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "EMBEDDING_API_KEY": "test-key",
            }
        ),
        encoding="utf-8",
    )
    seen = {}

    class FakeCollection:
        name = "national_formulary_v2"

        def count(self):
            return 10

        def query(self, **kwargs):
            seen["query_kwargs"] = kwargs
            return {
                "ids": [["doc-1"]],
                "documents": [["测试文档内容"]],
                "metadatas": [[{"source": "source.txt"}]],
                "distances": [[0.12]],
            }

    class FakeClient:
        def __init__(self, path):
            seen["path"] = path

        def get_collection(self, name):
            seen["collection"] = name
            return FakeCollection()

        def list_collections(self):
            return []

    def fake_embedding(model, base_url, api_key, query):
        seen["embedding"] = {
            "model": model,
            "base_url": base_url,
            "api_key": api_key,
            "query": query,
        }
        return [0.1] * 1024

    monkeypatch.setitem(sys.modules, "chromadb", SimpleNamespace(PersistentClient=FakeClient))
    monkeypatch.setattr(preview, "_call_openai_compatible_embedding", fake_embedding)

    project = create_default_project("Chroma 知识库")
    project.state.fields.append(StateField(name="retrieved_context", type="str"))
    project.nodes.extend(
        [
            NodeIR(
                id="retriever_context",
                type=NodeType.RETRIEVER,
                label="检索 Chroma",
                config={
                    "source": "vectorstore",
                    "path": str(chroma_dir),
                    "query": "{{ state.messages }}",
                    "topK": 3,
                    "outputField": "retrieved_context",
                    "embeddingModel": "bge-m3",
                },
            ),
            NodeIR(
                id="reply_final",
                type=NodeType.DIRECT_REPLY,
                label="回复",
                config={"template": "{{ state.retrieved_context }}", "outputField": "final_answer"},
            ),
        ]
    )
    project.edges.extend(
        [
            EdgeIR(id="e1", source="start", target="retriever_context"),
            EdgeIR(id="e2", source="retriever_context", target="reply_final"),
        ]
    )

    trace, state = preview.run_project_preview(project, {"messages": "测试查询"}, "live")

    assert {item["status"] for item in trace} == {"ok"}
    assert seen["path"] == str(chroma_dir)
    assert seen["collection"] == "national_formulary_v2"
    assert seen["embedding"] == {
        "model": "text-embedding-v4",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key": "test-key",
        "query": "测试查询",
    }
    assert seen["query_kwargs"]["query_embeddings"] == [[0.1] * 1024]
    assert seen["query_kwargs"]["n_results"] == 3
    assert "source.txt" in state["retrieved_context"]
    assert "测试文档内容" in state["retrieved_context"]


def test_live_preview_runs_customer_support_order_and_refund_paths(monkeypatch):
    calls: list[list[tuple[str, str]]] = []

    def fake_call_chat_model(provider, model, messages, runtime_config=None):
        calls.append(messages)
        user_content = messages[-1][1]
        if "SF1234567890" in user_content:
            return FakeResponse("您的订单 A20260614001 已发货，顺丰单号 SF1234567890，预计明天 18:00 前送达。")
        return FakeResponse("退款申请已收到，已根据审批结果继续处理。")

    monkeypatch.setattr(preview, "_call_chat_model", fake_call_chat_model)
    project = _customer_support_project()

    trace, state = preview.run_project_preview(
        project,
        {"messages": "我想查询订单物流，订单号是 A20260614001", "order_id": "A20260614001"},
        "live",
        {"provider": "openai", "model": "gpt-4.1-mini", "enabled": True},
    )

    assert [item["nodeId"] for item in trace] == ["route_intent", "query_order", "support_agent", "reply_support"]
    assert {item["status"] for item in trace} == {"ok"}
    assert state["route_key"] == "order"
    assert state["order_info"]["tracking_no"] == "SF1234567890"
    assert "顺丰单号" in state["final_answer"]

    refund_trace, refund_state = preview.run_project_preview(
        project,
        {"messages": "我要申请退款", "approval_action": "approved"},
        "live",
        {"provider": "openai", "model": "gpt-4.1-mini", "enabled": True},
    )

    assert [item["nodeId"] for item in refund_trace] == ["route_intent", "refund_approval", "support_agent", "reply_support"]
    assert {item["status"] for item in refund_trace} == {"ok"}
    assert refund_state["route_key"] == "refund"
    assert refund_state["approval_action"] == "approved"
    assert "退款申请" in refund_state["final_answer"]
    assert len(calls) == 2


def _customer_support_project():
    project = create_default_project("客服工单 Agent")
    project.state.fields.extend(
        [
            StateField(name="route_key", type="str"),
            StateField(name="route_reason", type="str"),
            StateField(name="order_id", type="str"),
            StateField(name="order_info", type="dict"),
            StateField(name="approval_action", type="str"),
            StateField(name="approval_result", type="dict"),
            StateField(name="agent_result", type="str"),
            StateField(name="final_answer", type="str"),
        ]
    )
    project.nodes.extend(
        [
            NodeIR(
                id="route_intent",
                type=NodeType.AI_ROUTER,
                label="识别问题类型",
                config={
                    "inputText": "{{ state.messages }}",
                    "scenarios": "order:订单问题:订单,物流,发货,快递\nrefund:退款问题:退款,退货,赔付,取消\nother:其他问题:",
                    "routeField": "route_key",
                    "reasonField": "route_reason",
                    "fallback": "other",
                },
            ),
            NodeIR(
                id="query_order",
                type=NodeType.HTTP,
                label="查询订单 API",
                config={
                    "method": "GET",
                    "url": "https://api.example.com/orders/{{ state.order_id }}",
                    "mockEnabled": True,
                    "mockResponseJson": '{"order_id":"{{ state.order_id }}","status":"已发货","tracking_no":"SF1234567890"}',
                    "outputField": "order_info",
                },
            ),
            NodeIR(
                id="refund_approval",
                type=NodeType.HUMAN_APPROVAL,
                label="退款人工审批",
                config={
                    "prompt": "用户请求退款，请人工确认是否批准。",
                    "actionField": "approval_action",
                    "outputField": "approval_result",
                    "defaultAction": "approved",
                    "fallback": "rejected",
                },
            ),
            NodeIR(
                id="support_agent",
                type=NodeType.AGENT,
                label="组织客服回复",
                config={
                    "systemPrompt": "你是售后客服 Agent。",
                    "userPrompt": "用户输入：{{ state.messages }}\n订单信息：{{ state.order_info }}\n审批结果：{{ state.approval_result }}",
                    "outputField": "agent_result",
                },
            ),
            NodeIR(
                id="reply_support",
                type=NodeType.DIRECT_REPLY,
                label="回复用户",
                config={"template": "{{ state.agent_result }}", "outputField": "final_answer"},
            ),
        ]
    )
    project.edges.extend(
        [
            EdgeIR(id="edge_start_route", source="start", target="route_intent"),
            EdgeIR(id="edge_route_order", source="route_intent", sourceHandle="order", target="query_order", kind=EdgeKind.CONDITIONAL),
            EdgeIR(id="edge_route_refund", source="route_intent", sourceHandle="refund", target="refund_approval", kind=EdgeKind.CONDITIONAL),
            EdgeIR(id="edge_route_other", source="route_intent", sourceHandle="other", target="support_agent", kind=EdgeKind.CONDITIONAL),
            EdgeIR(id="edge_order_agent", source="query_order", target="support_agent"),
            EdgeIR(id="edge_refund_ok", source="refund_approval", sourceHandle="approved", target="support_agent", kind=EdgeKind.CONDITIONAL),
            EdgeIR(id="edge_refund_rejected", source="refund_approval", sourceHandle="rejected", target="support_agent", kind=EdgeKind.CONDITIONAL),
            EdgeIR(id="edge_agent_reply", source="support_agent", target="reply_support"),
        ]
    )
    return project
