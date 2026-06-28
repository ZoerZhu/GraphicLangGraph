import json
import sys
from types import SimpleNamespace
from pathlib import Path

from app import mcp_runtime
from app.ir.schemas import EdgeIR, EdgeKind, ImportedAgentConfig, MCPServerConfig, NodeIR, NodeType, SkillConfig, StateField, ToolConfig, create_default_project
from app.runner import engine, model_runtime, preview, walk_runtime
from app.runner.nodes import http as http_node
from app.runner.nodes import task_splitter as task_splitter_node
from app.runner.trace import run_status_from_state
from app.runner.tool_runtime import registry as tool_runtime_registry
from app.runner.tool_runtime import web as tool_runtime_web


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

    monkeypatch.setattr(model_runtime, "call_chat_model", fake_call_chat_model)

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

    monkeypatch.setattr(model_runtime, "call_chat_model", fake_call_chat_model)

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

    monkeypatch.setattr(model_runtime, "call_chat_model", fake_call_chat_model)

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

    monkeypatch.setattr(model_runtime, "call_chat_model", fake_call_chat_model)

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


def test_live_preview_injects_skill_package_references(monkeypatch):
    seen = {}

    def fake_call_chat_model(provider, model, messages, runtime_config=None):
        seen["messages"] = messages
        return FakeResponse("已按 Skill 包输出")

    monkeypatch.setattr(model_runtime, "call_chat_model", fake_call_chat_model)

    metadata = {
        "packageMetadata": {"version": "1.0.0", "category": "Frontend"},
        "relatedMarkdown": [
            {
                "path": "writer/notes.md",
                "title": "Notes",
                "content": "关联说明：输出必须包含验收标准。",
            }
        ],
        "supportFiles": [
            {"path": "writer/scripts/format.sh", "kind": "script", "size": 22, "preview": "echo format"},
            {"path": "writer/assets/template.txt", "kind": "asset", "size": 12},
        ],
    }
    project = create_default_project("Skill 包注入测试")
    project.skills.append(
        SkillConfig(
            id="skill_package",
            name="写作 Skill 包",
            description="带 references 的 Skill",
            content="核心规则：先给结论。",
            metadata_json=json.dumps(metadata, ensure_ascii=False),
        )
    )
    project.nodes.append(
        NodeIR(
            id="package_agent",
            type=NodeType.AGENT,
            label="包 Agent",
            config={
                "systemPrompt": "你是写作助手。",
                "skillIdsJson": '["skill_package"]',
                "outputField": "agent_result",
            },
        )
    )
    project.edges.append(EdgeIR(id="e1", source="start", target="package_agent"))

    _trace, state = preview.run_project_preview(project, {"messages": "写总结"}, "live")

    assert state["agent_result"] == "已按 Skill 包输出"
    system_prompt = seen["messages"][0][1]
    assert "核心规则：先给结论" in system_prompt
    assert "Related References" in system_prompt
    assert "关联说明：输出必须包含验收标准" in system_prompt
    assert "Support Files" in system_prompt
    assert "writer/scripts/format.sh" in system_prompt
    assert "writer/assets/template.txt" in system_prompt


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


def test_live_preview_mcp_node_calls_configured_tool(monkeypatch):
    seen = {}

    def fake_invoke(server_config, tool_name, args, runtime_environment=None):
        seen["server"] = server_config
        seen["tool_name"] = tool_name
        seen["args"] = args
        return {
            "ok": True,
            "serverId": server_config["id"],
            "serverName": server_config["name"],
            "tool": tool_name,
            "args": args,
            "content": "Exa result",
            "raw": {"items": [{"title": "Result"}]},
        }

    monkeypatch.setattr(mcp_runtime, "invoke_mcp_tool", fake_invoke)

    project = create_default_project("MCP Node 测试")
    project.mcpServers.append(
        MCPServerConfig(
            id="mcp_exa",
            name="Exa MCP",
            transport="http",
            url="https://mcp.exa.ai/mcp",
        )
    )
    project.nodes.append(
        NodeIR(
            id="exa_search",
            type=NodeType.MCP_NODE,
            label="Exa MCP",
            config={
                "serverId": "mcp_exa",
                "serverName": "Exa MCP",
                "toolName": "web_search_exa",
                "toolArgsJson": '{"query":"{{ state.messages }}"}',
                "outputField": "mcp_result",
            },
        )
    )
    project.edges.append(EdgeIR(id="e1", source="start", target="exa_search"))

    trace, state = preview.run_project_preview(project, {"messages": "LangGraph MCP"}, "live")

    assert trace[0]["status"] == "ok"
    assert seen["tool_name"] == "web_search_exa"
    assert seen["args"] == {"query": "LangGraph MCP"}
    assert state["mcp_result"]["ok"] is True
    assert state["mcp_result"]["content"] == "Exa result"


def test_live_preview_mcp_node_auto_selects_single_tool(monkeypatch):
    seen = {}

    def fake_list_tools(server_config, runtime_environment=None, require_enabled=True):
        return [{"name": "only_tool", "description": "Only tool", "inputSchema": {"type": "object", "properties": {}}}]

    def fake_invoke(server_config, tool_name, args, runtime_environment=None):
        seen["tool_name"] = tool_name
        seen["args"] = args
        return {"ok": True, "serverId": server_config["id"], "serverName": server_config["name"], "tool": tool_name, "args": args, "content": "ok", "raw": {}}

    monkeypatch.setattr(mcp_runtime, "list_mcp_tools", fake_list_tools)
    monkeypatch.setattr(mcp_runtime, "invoke_mcp_tool", fake_invoke)

    project = create_default_project("MCP Auto Single")
    project.mcpServers.append(MCPServerConfig(id="mcp_one", name="One MCP", transport="http", url="https://mcp.example.com/mcp"))
    project.nodes.append(
        NodeIR(
            id="mcp_node",
            type=NodeType.MCP_NODE,
            label="MCP",
            config={"serverId": "mcp_one", "serverName": "One MCP", "toolArgsJson": "{}", "outputField": "mcp_result"},
        )
    )
    project.edges.append(EdgeIR(id="e1", source="start", target="mcp_node"))

    trace, state = preview.run_project_preview(project, {"messages": "hello"}, "live")

    assert trace[0]["status"] == "ok"
    assert seen == {"tool_name": "only_tool", "args": {}}
    assert state["mcp_result"]["autoSelectedTool"] is True
    assert state["mcp_result"]["availableTools"][0]["name"] == "only_tool"


def test_live_preview_mcp_node_auto_selects_exa_search_and_query(monkeypatch):
    seen = {}

    def fake_list_tools(server_config, runtime_environment=None, require_enabled=True):
        return [
            {"name": "web_fetch_exa", "inputSchema": {"type": "object", "properties": {"url": {"type": "string"}}}},
            {"name": "web_search_exa", "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
        ]

    def fake_invoke(server_config, tool_name, args, runtime_environment=None):
        seen["tool_name"] = tool_name
        seen["args"] = args
        return {"ok": True, "serverId": server_config["id"], "serverName": server_config["name"], "tool": tool_name, "args": args, "content": "search ok", "raw": {}}

    monkeypatch.setattr(mcp_runtime, "list_mcp_tools", fake_list_tools)
    monkeypatch.setattr(mcp_runtime, "invoke_mcp_tool", fake_invoke)

    project = create_default_project("MCP Auto Exa")
    project.mcpServers.append(MCPServerConfig(id="mcp_exa", name="Exa MCP", transport="http", url="https://mcp.exa.ai/mcp"))
    project.nodes.append(
        NodeIR(
            id="mcp_node",
            type=NodeType.MCP_NODE,
            label="Exa",
            config={"serverId": "mcp_exa", "serverName": "Exa MCP", "toolArgsJson": "{}", "outputField": "mcp_result"},
        )
    )
    project.edges.append(EdgeIR(id="e1", source="start", target="mcp_node"))

    trace, state = preview.run_project_preview(project, {"chat": "搜索 MCP runtime"}, "live")

    assert trace[0]["status"] == "ok"
    assert seen == {"tool_name": "web_search_exa", "args": {"query": "搜索 MCP runtime"}}
    assert state["mcp_result"]["autoSelectedTool"] is True


def test_live_preview_mcp_node_model_selects_tool_and_args(monkeypatch):
    calls = {"model": 0, "invoke": []}

    def fake_list_tools(server_config, runtime_environment=None, require_enabled=True):
        return [
            {"name": "web_fetch_exa", "inputSchema": {"type": "object", "properties": {"url": {"type": "string"}}}},
            {"name": "web_search_exa", "description": "Search web", "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
        ]

    def fake_call_chat_model(provider, model, messages, runtime_config=None):
        calls["model"] += 1
        assert provider == "openai"
        assert model == "gpt-4.1-mini"
        assert "web_search_exa" in messages[0][1]
        return FakeResponse(json.dumps({"tool": "web_search_exa", "args": {"query": "模型选择 MCP"}, "reason": "需要搜索"}, ensure_ascii=False))

    def fake_invoke(server_config, tool_name, args, runtime_environment=None):
        calls["invoke"].append({"tool": tool_name, "args": args})
        return {"ok": True, "serverId": server_config["id"], "serverName": server_config["name"], "tool": tool_name, "args": args, "content": "ok", "raw": {}}

    monkeypatch.setattr(mcp_runtime, "list_mcp_tools", fake_list_tools)
    monkeypatch.setattr(model_runtime, "call_chat_model", fake_call_chat_model)
    monkeypatch.setattr(mcp_runtime, "invoke_mcp_tool", fake_invoke)

    project = create_default_project("MCP Model Select")
    project.mcpServers.append(MCPServerConfig(id="mcp_exa", name="Exa MCP", transport="http", url="https://mcp.exa.ai/mcp"))
    project.nodes.append(
        NodeIR(
            id="mcp_node",
            type=NodeType.MCP_NODE,
            label="Exa",
            config={
                "serverId": "mcp_exa",
                "serverName": "Exa MCP",
                "toolSelectionMode": "model",
                "toolArgsJson": '{"numResults": 3}',
                "outputField": "mcp_result",
            },
        )
    )
    project.edges.append(EdgeIR(id="e1", source="start", target="mcp_node"))

    trace, state = preview.run_project_preview(project, {"messages": "查 MCP"}, "live")

    assert trace[0]["status"] == "ok"
    assert calls["model"] == 1
    assert calls["invoke"] == [{"tool": "web_search_exa", "args": {"numResults": 3, "query": "模型选择 MCP"}}]
    assert state["mcp_result"]["autoSelectedTool"] is True
    assert state["mcp_result"]["selectedByModel"] is True
    assert state["mcp_result"]["selectionMode"] == "model"
    assert state["mcp_result"]["selectionReason"] == "需要搜索"


def test_live_preview_mcp_node_model_select_invalid_tool_errors(monkeypatch):
    def fake_list_tools(server_config, runtime_environment=None, require_enabled=True):
        return [{"name": "web_search_exa"}]

    monkeypatch.setattr(mcp_runtime, "list_mcp_tools", fake_list_tools)
    monkeypatch.setattr(model_runtime, "call_chat_model", lambda *args, **kwargs: FakeResponse('{"tool":"missing_tool","args":{}}'))

    project = create_default_project("MCP Model Invalid")
    project.mcpServers.append(MCPServerConfig(id="mcp_exa", name="Exa MCP", transport="http", url="https://mcp.exa.ai/mcp"))
    project.nodes.append(
        NodeIR(
            id="mcp_node",
            type=NodeType.MCP_NODE,
            label="Exa",
            config={"serverId": "mcp_exa", "serverName": "Exa MCP", "toolSelectionMode": "model"},
        )
    )
    project.edges.append(EdgeIR(id="e1", source="start", target="mcp_node"))

    trace, _state = preview.run_project_preview(project, {"messages": "hello"}, "live")

    assert trace[0]["status"] == "error"
    assert "不存在或不可用" in trace[0]["detail"]


def test_live_preview_mcp_node_auto_select_reports_ambiguous_tools(monkeypatch):
    def fake_list_tools(server_config, runtime_environment=None, require_enabled=True):
        return [{"name": "web_fetch_exa"}, {"name": "read_page"}]

    monkeypatch.setattr(mcp_runtime, "list_mcp_tools", fake_list_tools)

    project = create_default_project("MCP Auto Ambiguous")
    project.mcpServers.append(MCPServerConfig(id="mcp_exa", name="Exa MCP", transport="http", url="https://mcp.exa.ai/mcp"))
    project.nodes.append(NodeIR(id="mcp_node", type=NodeType.MCP_NODE, label="Exa", config={"serverId": "mcp_exa", "serverName": "Exa MCP"}))
    project.edges.append(EdgeIR(id="e1", source="start", target="mcp_node"))

    trace, _state = preview.run_project_preview(project, {"messages": "hello"}, "live")

    assert trace[0]["status"] == "error"
    assert "web_fetch_exa" in trace[0]["detail"]
    assert "read_page" in trace[0]["detail"]


def test_live_preview_agent_can_call_selected_mcp_tool(monkeypatch):
    calls = {"model": 0, "mcp": []}

    def fake_list_tools(server_config, runtime_environment=None, require_enabled=True):
        assert require_enabled is True
        return [
            {
                "name": "web_search_exa",
                "title": "Web Search",
                "description": "Search web",
                "inputSchema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            }
        ]

    def fake_invoke(server_config, tool_name, args, runtime_environment=None):
        calls["mcp"].append({"server": server_config["id"], "tool": tool_name, "args": args})
        return {
            "ok": True,
            "serverId": server_config["id"],
            "serverName": server_config["name"],
            "tool": tool_name,
            "args": args,
            "content": "搜索结果：MCP runtime 已可用。",
            "raw": {},
        }

    def fake_call_chat_model(provider, model, messages, runtime_config=None):
        calls["model"] += 1
        if calls["model"] == 1:
            return FakeResponse(
                json.dumps(
                    {
                        "tool_calls": [
                            {
                                "tool": "mcp_mcp_exa__web_search_exa",
                                "args": {"query": "MCP runtime"},
                            }
                        ],
                        "final_answer": "",
                    },
                    ensure_ascii=False,
                )
            )
        return FakeResponse(json.dumps({"tool_calls": [], "final_answer": "Exa 查询完成"}, ensure_ascii=False))

    monkeypatch.setattr(mcp_runtime, "list_mcp_tools", fake_list_tools)
    monkeypatch.setattr(mcp_runtime, "invoke_mcp_tool", fake_invoke)
    monkeypatch.setattr(model_runtime, "call_chat_model", fake_call_chat_model)

    project = create_default_project("Agent MCP 测试")
    project.mcpServers.append(
        MCPServerConfig(
            id="mcp_exa",
            name="Exa MCP",
            transport="http",
            url="https://mcp.exa.ai/mcp",
        )
    )
    project.nodes.append(
        NodeIR(
            id="agent",
            type=NodeType.AGENT,
            label="Agent",
            config={
                "systemPrompt": "你可以使用 MCP 搜索。",
                "mcpServerIdsJson": '["mcp_exa"]',
                "mcpServerRegistryJson": json.dumps([project.mcpServers[0].model_dump(by_alias=True)], ensure_ascii=False),
                "outputField": "agent_result",
                "maxIterations": 3,
            },
        )
    )
    project.edges.append(EdgeIR(id="e1", source="start", target="agent"))

    trace, state = preview.run_project_preview(project, {"messages": "查 MCP runtime"}, "live")

    assert trace[0]["status"] == "ok"
    assert state["agent_result"] == "Exa 查询完成"
    assert state["agent_result_mcp_tool_calls"][0]["tool"] == "mcp_mcp_exa__web_search_exa"
    assert calls["mcp"] == [{"server": "mcp_exa", "tool": "web_search_exa", "args": {"query": "MCP runtime"}}]


def test_live_preview_agent_can_call_imported_agent_as_tool(monkeypatch):
    calls = {"model": 0}
    child_project = create_default_project("Child Agent")
    child_project.project.id = "child_agent"
    child_project.nodes.append(
        NodeIR(
            id="reply",
            type=NodeType.DIRECT_REPLY,
            label="Child Reply",
            config={"template": "子 Agent 收到：{{ state.messages }}", "outputField": "final_answer"},
        )
    )
    child_project.edges.append(EdgeIR(id="child_e1", source="start", target="reply"))

    def fake_read_project(project_id):
        assert project_id == "child_agent"
        return child_project

    def fake_call_chat_model(provider, model, messages, runtime_config=None):
        calls["model"] += 1
        if calls["model"] == 1:
            return FakeResponse(
                json.dumps(
                    {"tool_calls": [{"tool": "agent_agent_ref_child", "args": {"input": "处理退款问题"}}], "final_answer": ""},
                    ensure_ascii=False,
                )
            )
        return FakeResponse(json.dumps({"tool_calls": [], "final_answer": "子 Agent 已处理"}, ensure_ascii=False))

    monkeypatch.setattr(walk_runtime, "read_project", fake_read_project)
    monkeypatch.setattr(model_runtime, "call_chat_model", fake_call_chat_model)

    project = create_default_project("Parent Agent")
    imported = ImportedAgentConfig(id="agent_ref_child", name="Child Agent", projectId="child_agent", role="sub_agent")
    project.importedAgents.append(imported)
    project.nodes.append(
        NodeIR(
            id="agent",
            type=NodeType.AGENT,
            label="Parent",
            config={
                "systemPrompt": "你可以调用子 Agent。",
                "agentIdsJson": '["agent_ref_child"]',
                "agentRegistryJson": json.dumps([imported.model_dump(by_alias=True)], ensure_ascii=False),
                "outputField": "agent_result",
            },
        )
    )
    project.edges.append(EdgeIR(id="e1", source="start", target="agent"))

    trace, state = preview.run_project_preview(project, {"messages": "需要退款"}, "live")

    assert trace[0]["status"] == "ok"
    assert state["agent_result"] == "子 Agent 已处理"
    call = state["agent_result_agent_tool_calls"][0]
    assert call["source"] == "agent"
    assert call["agentName"] == "Child Agent"
    assert call["observation"]["result"]["finalAnswer"] == "子 Agent 收到：处理退款问题"


def test_live_preview_agent_ref_executes_bound_project(monkeypatch):
    child_project = create_default_project("Child Ref Agent")
    child_project.project.id = "child_ref"
    child_project.nodes.append(
        NodeIR(
            id="reply",
            type=NodeType.DIRECT_REPLY,
            label="Child Reply",
            config={"template": "ref: {{ state.messages }}", "outputField": "final_answer"},
        )
    )
    child_project.edges.append(EdgeIR(id="child_e1", source="start", target="reply"))

    monkeypatch.setattr(walk_runtime, "read_project", lambda project_id: child_project)

    project = create_default_project("Parent Ref")
    project.nodes.append(
        NodeIR(
            id="agent_ref",
            type=NodeType.AGENT_REF,
            label="Child Ref",
            config={"agentProjectId": "child_ref", "agentName": "Child Ref Agent", "instruction": "处理：{{ state.messages }}", "outputField": "child_result"},
        )
    )
    project.edges.append(EdgeIR(id="e1", source="start", target="agent_ref"))

    trace, state = preview.run_project_preview(project, {"messages": "订单"}, "live")

    assert trace[0]["status"] == "ok"
    assert state["child_result"]["ok"] is True
    assert state["child_result"]["finalAnswer"] == "ref: 处理：订单"


def test_live_preview_agent_ref_rejects_self_call():
    project = create_default_project("Self Ref")
    project.nodes.append(
        NodeIR(
            id="agent_ref",
            type=NodeType.AGENT_REF,
            label="Self",
            config={"agentProjectId": project.project.id, "agentName": "Self"},
        )
    )
    project.edges.append(EdgeIR(id="e1", source="start", target="agent_ref"))

    trace, _state = preview.run_project_preview(project, {"messages": "hello"}, "live")

    assert trace[0]["status"] == "error"
    assert "当前项目自身" in trace[0]["detail"]


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

    monkeypatch.setattr(model_runtime, "call_chat_model", fake_call_chat_model)

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


def test_tools_agent_task_plan_tool_outputs_splitter_tasks(monkeypatch):
    seen_messages = []

    def fake_call_chat_model(provider, model, messages, runtime_config=None):
        seen_messages.append(messages)
        if len(seen_messages) == 1:
            return FakeResponse(
                json.dumps(
                    {
                        "tool_calls": [
                            {
                                "tool": "task_plan",
                                "args": {
                                    "tasks": [
                                        {
                                            "title": "分析入口",
                                            "goal": "阅读入口文件和路由",
                                            "targetFiles": ["backend/app/main.py"],
                                            "suggestedTools": ["read_file_chunk"],
                                        },
                                        {"title": "分析前端", "goal": "阅读前端工作区组件"},
                                    ]
                                },
                            }
                        ],
                        "final_answer": "",
                    },
                    ensure_ascii=False,
                )
            )
        return FakeResponse(json.dumps({"tool_calls": [], "final_answer": "任务计划已生成"}, ensure_ascii=False))

    monkeypatch.setattr(model_runtime, "call_chat_model", fake_call_chat_model)

    project = create_default_project("Task Plan Tool")
    project.state.fields.extend(
        [
            StateField(name="task_plan", type="str"),
            StateField(name="task_plan_tool_calls", type="list"),
            StateField(name="worker_tasks", type="list"),
        ]
    )
    project.tools.append(
        ToolConfig(
            id="builtin_task_plan",
            name="task_plan",
            description="规划任务",
            source="builtin",
            schemaJson=json.dumps({"type": "object", "x-graphic": {"kind": "builtin_tool", "builtinId": "task_plan"}}),
        )
    )
    project.nodes.extend(
        [
            NodeIR(
                id="tools_agent",
                type=NodeType.TOOL,
                label="Tools",
                config={"toolIdsJson": '["builtin_task_plan"]', "outputField": "task_plan", "maxIterations": 2},
            ),
            NodeIR(
                id="splitter",
                type=NodeType.TASK_SPLITTER,
                label="Task Splitter",
                config={"inputField": "task_plan", "outputField": "worker_tasks", "maxTasks": 5, "fallbackToSingleTask": False},
            ),
        ]
    )
    project.edges.extend([EdgeIR(id="e1", source="start", target="tools_agent"), EdgeIR(id="e2", source="tools_agent", target="splitter")])

    trace, state = preview.run_project_preview(project, {"messages": "分析项目"}, "live")

    assert [item["status"] for item in trace] == ["ok", "ok"]
    assert "Task Splitter 任务规划" in seen_messages[0][0][1]
    parsed_plan = json.loads(state["task_plan"])
    assert len(parsed_plan["tasks"]) == 2
    assert state["worker_tasks"][0]["title"] == "分析入口"
    assert state["worker_tasks"][0]["targetFiles"] == ["backend/app/main.py"]
    assert state["task_plan_tool_calls"][0]["tool"] == "task_plan"


def test_workflow_core_variable_assign_and_template_live_run():
    project = create_default_project("Workflow Core")
    project.state.fields.extend(
        [
            StateField(name="assigned_value", type="str"),
            StateField(name="list_value", type="list"),
            StateField(name="merged_value", type="dict"),
            StateField(name="assignment_result", type="dict"),
            StateField(name="template_result", type="dict"),
            StateField(name="final_answer", type="str"),
        ]
    )
    project.nodes.extend(
        [
            NodeIR(
                id="assign",
                type=NodeType.VARIABLE_ASSIGN,
                label="Variable Assign",
                config={
                    "assignmentsJson": json.dumps(
                        [
                            {"target": "assigned_value", "operation": "overwrite", "sourceType": "state", "source": "messages", "valueType": "string"},
                            {"target": "list_value", "operation": "append", "sourceType": "literal", "source": "item", "valueType": "string"},
                            {"target": "merged_value", "operation": "merge", "sourceType": "json", "source": '{"ok": true}', "valueType": "json"},
                        ]
                    ),
                    "resultField": "assignment_result",
                },
            ),
            NodeIR(
                id="template",
                type=NodeType.TEMPLATE,
                label="Template",
                config={
                    "template": '{"message":"{{ state.assigned_value }}","ok":true}',
                    "outputType": "json",
                    "outputField": "template_result",
                },
            ),
            NodeIR(id="reply", type=NodeType.DIRECT_REPLY, label="回复", config={"template": "{{ state.template_result }}", "outputField": "final_answer"}),
        ]
    )
    project.edges.extend([EdgeIR(id="e1", source="start", target="assign"), EdgeIR(id="e2", source="assign", target="template"), EdgeIR(id="e3", source="template", target="reply")])

    trace, state = preview.run_project_preview(project, {"messages": "hello"}, "live")

    assert [item["status"] for item in trace] == ["ok", "ok", "ok"]
    assert state["assigned_value"] == "hello"
    assert state["list_value"] == ["item"]
    assert state["merged_value"] == {"ok": True}
    assert state["assignment_result"]["changedFields"] == ["assigned_value", "list_value", "merged_value"]
    assert state["template_result"] == {"message": "hello", "ok": True}


def test_workflow_core_trace_includes_data_shaping_metadata():
    project = create_default_project("Workflow Core Trace")
    schema_fields = json.dumps(
        [
            {"name": "orderId", "type": "string", "required": True},
            {"name": "status", "type": "string", "required": True},
        ]
    )
    project.nodes.extend(
        [
            NodeIR(
                id="assign",
                type=NodeType.VARIABLE_ASSIGN,
                label="Variable Assign",
                config={
                    "inputMappingsJson": json.dumps([{"name": "order", "sourceType": "state", "source": "order", "valueType": "json"}]),
                    "assignmentsJson": json.dumps(
                        [
                            {
                                "target": "clean_order",
                                "operation": "overwrite",
                                "sourceType": "input",
                                "source": "order",
                                "transform": "pick",
                                "transformArgsJson": '{"paths":["orderId","status"]}',
                                "valueType": "json",
                            }
                        ]
                    ),
                    "resultField": "assignment_result",
                },
            ),
            NodeIR(
                id="validator",
                type=NodeType.JSON_VALIDATOR,
                label="JSON Validator",
                config={
                    "inputField": "clean_order",
                    "schemaFieldsJson": schema_fields,
                    "outputField": "clean_order",
                    "validationField": "order_validation",
                },
                outputs=[{"id": "valid", "type": "condition", "label": "valid"}, {"id": "invalid", "type": "condition", "label": "invalid"}],
            ),
        ]
    )
    project.edges.extend([EdgeIR(id="e1", source="start", target="assign"), EdgeIR(id="e2", source="assign", target="validator")])

    trace, state = preview.run_project_preview(project, {"order": {"orderId": "O-1", "status": "已发货", "secret": "hidden"}}, "live")

    assert state["clean_order"] == {"orderId": "O-1", "status": "已发货"}
    assert trace[0]["dataShaping"]["kind"] == "variable_assign"
    assert trace[0]["dataShaping"]["changedFields"] == ["clean_order"]
    assert trace[0]["dataShaping"]["assignments"][0]["transform"] == "pick"
    assert trace[1]["dataShaping"]["kind"] == "json_validator"
    assert trace[1]["dataShaping"]["validation"]["valid"] is True
    assert trace[1]["dataShaping"]["branch"] == "valid"


def test_json_extractor_valid_branch_feeds_task_splitter(monkeypatch):
    def fake_call_chat_model(provider, model, messages, runtime_config=None):
        return FakeResponse(json.dumps({"tasks": [{"title": "分析入口", "goal": "阅读入口文件"}]}, ensure_ascii=False))

    monkeypatch.setattr(model_runtime, "call_chat_model", fake_call_chat_model)

    project = create_default_project("Extractor Tasks")
    project.state.fields.extend(
        [
            StateField(name="extracted_json", type="dict"),
            StateField(name="validation_result", type="dict"),
            StateField(name="worker_tasks", type="list"),
            StateField(name="final_answer", type="str"),
        ]
    )
    schema_fields = json.dumps([{"name": "tasks", "type": "array", "required": True, "description": "任务数组"}])
    project.nodes.extend(
        [
            NodeIR(
                id="extract",
                type=NodeType.JSON_EXTRACTOR,
                label="JSON Extractor",
                config={
                    "inputText": "{{ state.messages }}",
                    "schemaFieldsJson": schema_fields,
                    "outputField": "extracted_json",
                    "validationField": "validation_result",
                },
                outputs=[
                    {"id": "valid", "type": "condition", "label": "valid"},
                    {"id": "invalid", "type": "condition", "label": "invalid"},
                ],
            ),
            NodeIR(id="splitter", type=NodeType.TASK_SPLITTER, label="Task Splitter", config={"inputField": "extracted_json", "outputField": "worker_tasks", "maxTasks": 5, "fallbackToSingleTask": False}),
            NodeIR(id="reply_valid", type=NodeType.DIRECT_REPLY, label="回复", config={"template": "{{ state.worker_tasks }}", "outputField": "final_answer"}),
            NodeIR(id="reply_invalid", type=NodeType.DIRECT_REPLY, label="无效回复", config={"template": "invalid", "outputField": "final_answer"}),
        ]
    )
    project.edges.extend(
        [
            EdgeIR(id="e1", source="start", target="extract"),
            EdgeIR(id="e2", source="extract", target="splitter", kind=EdgeKind.CONDITIONAL, sourceHandle="valid"),
            EdgeIR(id="e3", source="extract", target="reply_invalid", kind=EdgeKind.CONDITIONAL, sourceHandle="invalid"),
            EdgeIR(id="e4", source="splitter", target="reply_valid"),
        ]
    )

    trace, state = preview.run_project_preview(project, {"messages": "拆分任务"}, "live")

    assert [item["nodeId"] for item in trace] == ["extract", "splitter", "reply_valid"]
    assert state["validation_result"]["valid"] is True
    assert state["worker_tasks"][0]["title"] == "分析入口"


def test_json_validator_invalid_branch_is_business_route():
    project = create_default_project("Validator Invalid")
    project.state.fields.extend(
        [
            StateField(name="candidate", type="dict"),
            StateField(name="validated_json", type="dict"),
            StateField(name="validation_result", type="dict"),
            StateField(name="final_answer", type="str"),
        ]
    )
    schema_fields = json.dumps([{"name": "tasks", "type": "array", "required": True, "description": "任务数组"}])
    project.nodes.extend(
        [
            NodeIR(
                id="validator",
                type=NodeType.JSON_VALIDATOR,
                label="JSON Validator",
                config={
                    "inputField": "candidate",
                    "schemaFieldsJson": schema_fields,
                    "outputField": "validated_json",
                    "validationField": "validation_result",
                },
                outputs=[
                    {"id": "valid", "type": "condition", "label": "valid"},
                    {"id": "invalid", "type": "condition", "label": "invalid"},
                ],
            ),
            NodeIR(id="reply_valid", type=NodeType.DIRECT_REPLY, label="有效回复", config={"template": "valid", "outputField": "final_answer"}),
            NodeIR(id="reply_invalid", type=NodeType.DIRECT_REPLY, label="无效回复", config={"template": "invalid", "outputField": "final_answer"}),
        ]
    )
    project.edges.extend(
        [
            EdgeIR(id="e1", source="start", target="validator"),
            EdgeIR(id="e2", source="validator", target="reply_valid", kind=EdgeKind.CONDITIONAL, sourceHandle="valid"),
            EdgeIR(id="e3", source="validator", target="reply_invalid", kind=EdgeKind.CONDITIONAL, sourceHandle="invalid"),
        ]
    )

    trace, state = preview.run_project_preview(project, {"messages": "x", "candidate": {"tasks": "not a list"}}, "live")

    assert [item["nodeId"] for item in trace] == ["validator", "reply_invalid"]
    assert trace[0]["status"] == "ok"
    assert state["validation_result"]["valid"] is False
    assert state["final_answer"] == "invalid"


def test_workflow_core_v2_paths_transforms_and_task_plan_preset():
    project = create_default_project("Workflow Core v2")
    project.state.fields.extend(
        [
            StateField(name="joined_titles", type="str"),
            StateField(name="fallback_value", type="str"),
            StateField(name="picked_profile", type="dict"),
            StateField(name="task_validation", type="dict"),
        ]
    )
    project.nodes.extend(
        [
            NodeIR(
                id="assign",
                type=NodeType.VARIABLE_ASSIGN,
                label="Assign",
                config={
                    "assignmentsJson": json.dumps(
                        [
                            {
                                "target": "joined_titles",
                                "operation": "overwrite",
                                "sourceType": "state",
                                "source": "task_plan.tasks[].title",
                                "transform": "join",
                                "transformArgsJson": '{"separator": ","}',
                                "valueType": "string",
                            },
                            {
                                "target": "fallback_value",
                                "operation": "overwrite",
                                "sourceType": "state",
                                "source": "missing",
                                "transform": "coalesce",
                                "transformArgsJson": '{"candidates":[{"sourceType":"state","source":"messages"},"fallback"]}',
                                "valueType": "string",
                            },
                            {
                                "target": "picked_profile",
                                "operation": "overwrite",
                                "sourceType": "state",
                                "source": "profile",
                                "transform": "pick",
                                "transformArgsJson": '{"paths":["name"]}',
                                "valueType": "json",
                            },
                        ]
                    ),
                    "resultField": "assignment_result",
                },
            ),
            NodeIR(
                id="validator",
                type=NodeType.JSON_VALIDATOR,
                label="Validator",
                config={"inputField": "task_plan", "schemaPreset": "task_plan_v1", "validationField": "task_validation", "outputField": "validated_plan"},
            ),
        ]
    )
    project.edges.extend([EdgeIR(id="e1", source="start", target="assign"), EdgeIR(id="e2", source="assign", target="validator")])

    _trace, state = preview.run_project_preview(
        project,
        {
            "messages": "from message",
            "profile": {"name": "Ada", "secret": "hidden"},
            "task_plan": {"tasks": [{"title": "分析入口"}, {"goal": "阅读后端"}]},
        },
        "live",
    )

    assert state["joined_titles"] == "分析入口"
    assert state["fallback_value"] == "from message"
    assert state["picked_profile"] == {"name": "Ada"}
    assert state["task_validation"]["valid"] is True


def test_json_validator_repair_success_overwrites_output(monkeypatch):
    calls = []

    def fake_call_chat_model(provider, model, messages, runtime_config=None):
        calls.append(messages)
        return FakeResponse(json.dumps({"tasks": [{"goal": "修复后的任务"}]}, ensure_ascii=False))

    monkeypatch.setattr(model_runtime, "call_chat_model", fake_call_chat_model)

    project = create_default_project("Validator Repair")
    project.nodes.append(
        NodeIR(
            id="validator",
            type=NodeType.JSON_VALIDATOR,
            label="Validator",
            config={
                "inputField": "candidate",
                "schemaPreset": "task_plan_v1",
                "repairEnabled": True,
                "outputField": "validated_json",
                "validationField": "validation_result",
                "repairResultField": "repair_result",
            },
        )
    )
    project.edges.append(EdgeIR(id="e1", source="start", target="validator"))

    trace, state = preview.run_project_preview(project, {"candidate": {"tasks": [{"targetFiles": ["x.py"]}]}}, "live")

    assert trace[0]["status"] == "ok"
    assert len(calls) == 1
    assert state["validation_result"]["valid"] is True
    assert state["validated_json"]["tasks"][0]["goal"] == "修复后的任务"
    assert state["repair_result"]["ok"] is True


def test_json_extractor_non_json_repair_failure_routes_invalid(monkeypatch):
    def fake_call_chat_model(provider, model, messages, runtime_config=None):
        return FakeResponse("still not json")

    monkeypatch.setattr(model_runtime, "call_chat_model", fake_call_chat_model)

    project = create_default_project("Extractor Repair Failure")
    project.nodes.extend(
        [
            NodeIR(
                id="extract",
                type=NodeType.JSON_EXTRACTOR,
                label="Extractor",
                config={
                    "schemaPreset": "task_plan_v1",
                    "repairEnabled": True,
                    "outputField": "extracted_json",
                    "validationField": "validation_result",
                    "repairResultField": "repair_result",
                },
                outputs=[{"id": "valid", "type": "condition", "label": "valid"}, {"id": "invalid", "type": "condition", "label": "invalid"}],
            ),
            NodeIR(id="reply_invalid", type=NodeType.DIRECT_REPLY, label="Invalid", config={"template": "invalid", "outputField": "final_answer"}),
        ]
    )
    project.edges.extend([EdgeIR(id="e1", source="start", target="extract"), EdgeIR(id="e2", source="extract", target="reply_invalid", kind=EdgeKind.CONDITIONAL, sourceHandle="invalid")])

    trace, state = preview.run_project_preview(project, {"messages": "拆任务"}, "live")

    assert [item["nodeId"] for item in trace] == ["extract", "reply_invalid"]
    assert state["validation_result"]["valid"] is False
    assert state["repair_result"]["ok"] is False


def test_for_each_runs_item_chain_and_merge_reducers_isolated():
    project = create_default_project("ForEach Merge")
    project.state.fields.extend(
        [
            StateField(name="items", type="list"),
            StateField(name="merged_results", type="list"),
            StateField(name="concat_results", type="list"),
            StateField(name="merged_object", type="dict"),
            StateField(name="first_item", type="str"),
            StateField(name="last_item", type="str"),
            StateField(name="merge_result", type="dict"),
            StateField(name="final_answer", type="str"),
        ]
    )
    project.nodes.extend(
        [
            NodeIR(id="each", type=NodeType.FOR_EACH, label="ForEach", config={"itemsField": "items", "itemField": "current_item", "indexField": "current_index", "maxItems": 10}),
            NodeIR(
                id="assign_item",
                type=NodeType.VARIABLE_ASSIGN,
                label="Assign Item",
                config={
                    "assignmentsJson": json.dumps(
                        [
                            {"target": "item_result", "operation": "overwrite", "sourceType": "state", "source": "current_item", "valueType": "string"},
                            {"target": "list_part", "operation": "overwrite", "sourceType": "json", "source": '["{{ state.current_item }}"]', "valueType": "json"},
                            {"target": "object_part", "operation": "overwrite", "sourceType": "json", "source": '{"value":"{{ state.current_item }}"}', "valueType": "json"},
                        ]
                    ),
                    "resultField": "assignment_result",
                },
            ),
            NodeIR(
                id="merge",
                type=NodeType.MERGE,
                label="Merge",
                config={
                    "reducersJson": json.dumps(
                        [
                            {"target": "merged_results", "source": "item_result", "reducer": "append"},
                            {"target": "concat_results", "source": "list_part", "reducer": "concat"},
                            {"target": "merged_object", "source": "object_part", "reducer": "merge"},
                            {"target": "first_item", "source": "item_result", "reducer": "first"},
                            {"target": "last_item", "source": "item_result", "reducer": "last"},
                        ]
                    ),
                    "resultField": "merge_result",
                },
            ),
            NodeIR(id="reply", type=NodeType.DIRECT_REPLY, label="Reply", config={"template": "{{ state.merged_results }}", "outputField": "final_answer"}),
        ]
    )
    project.edges.extend(
        [
            EdgeIR(id="e1", source="start", target="each"),
            EdgeIR(id="e2", source="each", target="assign_item", sourceHandle="item"),
            EdgeIR(id="e3", source="assign_item", target="merge"),
            EdgeIR(id="e4", source="merge", target="reply"),
        ]
    )

    trace, state = preview.run_project_preview(project, {"messages": "run", "items": ["a", "b"]}, "live")

    assert [item["nodeId"] for item in trace] == ["each", "reply"]
    assert state["merged_results"] == ["a", "b"]
    assert state["concat_results"] == ["a", "b"]
    assert state["merged_object"] == {"value": "b"}
    assert state["first_item"] == "a"
    assert state["last_item"] == "b"
    assert state["merge_result"]["itemCount"] == 2
    assert [item["index"] for item in state["merge_result"]["iterations"]] == [0, 1]
    assert "current_item" not in state


def test_for_each_stream_emits_iteration_child_node_events():
    project = create_default_project("ForEach Stream")
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
            NodeIR(id="each", type=NodeType.FOR_EACH, label="ForEach", config={"itemsField": "items", "itemField": "current_item", "indexField": "current_index"}),
            NodeIR(
                id="assign_item",
                type=NodeType.VARIABLE_ASSIGN,
                label="Assign Item",
                config={
                    "assignmentsJson": json.dumps(
                        [{"target": "item_result", "operation": "overwrite", "sourceType": "state", "source": "current_item", "valueType": "string"}]
                    ),
                    "resultField": "assignment_result",
                },
            ),
            NodeIR(id="merge", type=NodeType.MERGE, label="Merge", config={"reducersJson": json.dumps([{"target": "merged_results", "source": "item_result", "reducer": "append"}]), "resultField": "merge_result"}),
            NodeIR(id="reply", type=NodeType.DIRECT_REPLY, label="Reply", config={"template": "{{ state.merged_results }}", "outputField": "final_answer"}),
        ]
    )
    project.edges.extend(
        [
            EdgeIR(id="e1", source="start", target="each"),
            EdgeIR(id="e2", source="each", target="assign_item", sourceHandle="item"),
            EdgeIR(id="e3", source="assign_item", target="merge"),
            EdgeIR(id="e4", source="merge", target="reply"),
        ]
    )

    events = list(preview.iter_project_preview_events(project, {"messages": "run", "items": ["a", "b"]}, "live"))

    child_starts = [event for event in events if event.get("event") == "node_start" and event.get("nodeId") == "assign_item"]
    child_ends = [event["traceItem"] for event in events if event.get("event") == "node_end" and event.get("traceItem", {}).get("nodeId") == "assign_item"]
    run_end = next(event for event in events if event.get("event") == "run_end")
    history_child_trace = [item for item in run_end["trace"] if item["nodeId"] == "assign_item"]

    assert [event["iterationIndex"] for event in child_starts] == [0, 1]
    assert [item["iterationIndex"] for item in child_ends] == [0, 1]
    assert all(item["parentNodeId"] == "each" for item in child_ends)
    assert [item["outputDelta"]["item_result"] for item in history_child_trace] == ["a", "b"]
    assert run_end["outputState"]["merged_results"] == ["a", "b"]


def test_for_each_item_error_can_route_to_error_handler_before_merge():
    project = create_default_project("ForEach Error")
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
            NodeIR(id="each", type=NodeType.FOR_EACH, label="ForEach", config={"itemsField": "items", "itemField": "current_item", "indexField": "current_index"}),
            NodeIR(id="bad_template", type=NodeType.TEMPLATE, label="Bad Template", config={"template": "{bad json", "outputType": "json", "outputField": "item_result"}),
            NodeIR(id="error_handler", type=NodeType.ERROR_HANDLER, label="Error Handler", config={"errorField": "last_error", "template": "handled {{ state.last_error }}", "outputField": "item_result"}),
            NodeIR(id="merge", type=NodeType.MERGE, label="Merge", config={"reducersJson": json.dumps([{"target": "merged_results", "source": "item_result", "reducer": "append"}]), "resultField": "merge_result"}),
            NodeIR(id="reply", type=NodeType.DIRECT_REPLY, label="Reply", config={"template": "{{ state.merged_results }}", "outputField": "final_answer"}),
        ]
    )
    project.edges.extend(
        [
            EdgeIR(id="e1", source="start", target="each"),
            EdgeIR(id="e2", source="each", target="bad_template", sourceHandle="item"),
            EdgeIR(id="e3", source="bad_template", target="error_handler", kind=EdgeKind.ERROR, sourceHandle="error"),
            EdgeIR(id="e4", source="error_handler", target="merge"),
            EdgeIR(id="e5", source="merge", target="reply"),
        ]
    )

    trace, state = preview.run_project_preview(project, {"messages": "run", "items": ["a"]}, "live")

    assert [item["status"] for item in trace] == ["ok", "ok"]
    assert state["merged_results"][0]["ok"] is False
    assert state["merged_results"][0]["error"]["nodeId"] == "bad_template"
    assert state["final_answer"]


def test_for_each_stream_shows_child_error_handler_iterations():
    project = create_default_project("ForEach Error Stream")
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
            NodeIR(id="each", type=NodeType.FOR_EACH, label="ForEach", config={"itemsField": "items", "itemField": "current_item", "indexField": "current_index"}),
            NodeIR(id="bad_template", type=NodeType.TEMPLATE, label="Bad Template", config={"template": "{bad json", "outputType": "json", "outputField": "item_result"}),
            NodeIR(id="error_handler", type=NodeType.ERROR_HANDLER, label="Error Handler", config={"errorField": "last_error", "template": "handled {{ state.last_error }}", "outputField": "item_result"}),
            NodeIR(id="merge", type=NodeType.MERGE, label="Merge", config={"reducersJson": json.dumps([{"target": "merged_results", "source": "item_result", "reducer": "append"}]), "resultField": "merge_result"}),
            NodeIR(id="reply", type=NodeType.DIRECT_REPLY, label="Reply", config={"template": "{{ state.merged_results }}", "outputField": "final_answer"}),
        ]
    )
    project.edges.extend(
        [
            EdgeIR(id="e1", source="start", target="each"),
            EdgeIR(id="e2", source="each", target="bad_template", sourceHandle="item"),
            EdgeIR(id="e3", source="bad_template", target="error_handler", kind=EdgeKind.ERROR, sourceHandle="error"),
            EdgeIR(id="e4", source="error_handler", target="merge"),
            EdgeIR(id="e5", source="merge", target="reply"),
        ]
    )

    events = list(preview.iter_project_preview_events(project, {"messages": "run", "items": ["a"]}, "live"))

    child_ends = [event["traceItem"] for event in events if event.get("event") == "node_end" and event.get("traceItem", {}).get("parentNodeId") == "each"]
    run_end = next(event for event in events if event.get("event") == "run_end")
    status, pending = run_status_from_state(run_end["trace"], run_end["outputState"])

    assert [(item["nodeId"], item["status"], item["iterationIndex"]) for item in child_ends] == [
        ("bad_template", "ok", 0),
        ("error_handler", "ok", 0),
    ]
    assert child_ends[0]["handledError"] is True
    assert child_ends[0]["errorTarget"] == "error_handler"
    assert status == "completed"
    assert pending is None
    assert run_end["outputState"]["merged_results"][0]["ok"] is False
    assert run_end["outputState"]["merge_result"]["iterations"][0]["index"] == 0


def test_top_level_error_edge_routes_to_error_handler():
    project = create_default_project("Top Error")
    project.state.fields.extend([StateField(name="error_result", type="dict"), StateField(name="final_answer", type="str")])
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
            EdgeIR(id="e2", source="bad_template", target="error_handler", kind=EdgeKind.ERROR, sourceHandle="error"),
            EdgeIR(id="e3", source="error_handler", target="reply"),
        ]
    )

    trace, state = preview.run_project_preview(project, {"messages": "run"}, "live")

    assert [item["nodeId"] for item in trace] == ["bad_template", "error_handler", "reply"]
    assert trace[0]["status"] == "ok"
    assert state["last_error"]["nodeId"] == "bad_template"
    assert state["error_result"]["ok"] is False


def test_runtime_policy_retries_node_until_success(monkeypatch):
    project = create_default_project("Retry Policy")
    project.state.fields.extend([StateField(name="http_response", type="dict"), StateField(name="final_answer", type="str")])
    project.nodes.extend(
        [
            NodeIR(
                id="unstable_http",
                type=NodeType.HTTP,
                label="Unstable HTTP",
                config={
                    "method": "GET",
                    "url": "https://example.com/retry",
                    "mockResponseJson": "",
                    "outputField": "http_response",
                    "retryPolicyJson": json.dumps({"enabled": True, "maxRetries": 2, "backoffMs": 0}),
                },
            ),
            NodeIR(id="reply", type=NodeType.DIRECT_REPLY, label="Reply", config={"template": "{{ state.http_response }}", "outputField": "final_answer"}),
        ]
    )
    project.edges.extend([EdgeIR(id="e1", source="start", target="unstable_http"), EdgeIR(id="e2", source="unstable_http", target="reply")])
    calls = {"count": 0}

    class FakeHttpResponse:
        text = ""

        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": True, "attempt": calls["count"]}

    def fake_request(*_args, **_kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("temporary failure")
        return FakeHttpResponse()

    monkeypatch.setattr(http_node.httpx, "request", fake_request)

    trace, state = preview.run_project_preview(project, {"messages": "run"}, "live")

    assert calls["count"] == 2
    assert trace[0]["attempts"][0]["status"] == "error"
    assert trace[0]["attempts"][1]["status"] == "ok"
    assert state["http_response"] == {"ok": True, "attempt": 2}


def test_runtime_policy_timeout_fallback_continues(monkeypatch):
    project = create_default_project("Timeout Fallback")
    project.state.fields.extend([StateField(name="fallback_result", type="str"), StateField(name="node_error", type="dict"), StateField(name="final_answer", type="str")])
    project.nodes.extend(
        [
            NodeIR(
                id="slow_http",
                type=NodeType.HTTP,
                label="Slow HTTP",
                config={
                    "method": "GET",
                    "url": "https://example.com/slow",
                    "mockResponseJson": "",
                    "outputField": "http_response",
                    "nodeTimeoutSec": 0.01,
                    "errorPolicy": "fallback",
                    "fallbackOutputJson": json.dumps({"fallback_result": "timeout fallback"}),
                    "errorOutputField": "node_error",
                },
            ),
            NodeIR(id="reply", type=NodeType.DIRECT_REPLY, label="Reply", config={"template": "{{ state.fallback_result }}", "outputField": "final_answer"}),
        ]
    )
    project.edges.extend([EdgeIR(id="e1", source="start", target="slow_http"), EdgeIR(id="e2", source="slow_http", target="reply")])

    def fake_request(*_args, **_kwargs):
        import time

        time.sleep(0.05)
        raise RuntimeError("should be ignored")

    monkeypatch.setattr(http_node.httpx, "request", fake_request)

    trace, state = preview.run_project_preview(project, {"messages": "run"}, "live")

    assert trace[0]["status"] == "ok"
    assert trace[0]["errorPolicy"] == "fallback"
    assert trace[0]["timeoutSec"] == 0.01
    assert state["fallback_result"] == "timeout fallback"
    assert state["node_error"]["errorType"] == "timeout"
    assert state["final_answer"] == "timeout fallback"


def test_runtime_policy_continue_writes_error_and_continues():
    project = create_default_project("Continue Policy")
    project.state.fields.extend([StateField(name="node_error", type="dict"), StateField(name="final_answer", type="str")])
    project.nodes.extend(
        [
            NodeIR(
                id="bad_template",
                type=NodeType.TEMPLATE,
                label="Bad Template",
                config={"template": "{bad json", "outputType": "json", "outputField": "broken", "errorPolicy": "continue", "errorOutputField": "node_error"},
            ),
            NodeIR(id="reply", type=NodeType.DIRECT_REPLY, label="Reply", config={"template": "{{ state.node_error }}", "outputField": "final_answer"}),
        ]
    )
    project.edges.extend([EdgeIR(id="e1", source="start", target="bad_template"), EdgeIR(id="e2", source="bad_template", target="reply")])

    trace, state = preview.run_project_preview(project, {"messages": "run"}, "live")

    assert trace[0]["status"] == "ok"
    assert trace[0]["errorPolicy"] == "continue"
    assert state["node_error"]["nodeId"] == "bad_template"
    assert state["final_answer"]


def test_parallel_for_each_collects_item_errors_and_preserves_order():
    project = create_default_project("Parallel ForEach")
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
                    "resultField": "for_each_result",
                },
            ),
            NodeIR(id="template", type=NodeType.TEMPLATE, label="Template", config={"template": '{"value":"{{ state.current_item }}"}', "outputType": "json", "outputField": "item_result"}),
            NodeIR(id="merge", type=NodeType.MERGE, label="Merge", config={"reducersJson": json.dumps([{"target": "merged_results", "source": "item_result", "reducer": "append"}]), "resultField": "merge_result"}),
            NodeIR(id="reply", type=NodeType.DIRECT_REPLY, label="Reply", config={"template": "{{ state.merged_results }}", "outputField": "final_answer"}),
        ]
    )
    project.edges.extend(
        [
            EdgeIR(id="e1", source="start", target="each"),
            EdgeIR(id="e2", source="each", target="template", sourceHandle="item"),
            EdgeIR(id="e3", source="template", target="merge"),
            EdgeIR(id="e4", source="merge", target="reply"),
        ]
    )

    trace, state = preview.run_project_preview(project, {"messages": "run", "items": ["a", 'bad " json', "c"]}, "live")

    assert trace[0]["parallel"] is True
    assert state["merged_results"][0] == {"value": "a"}
    assert state["merged_results"][1]["ok"] is False
    assert state["merged_results"][2] == {"value": "c"}
    assert state["merge_result"]["iterations"][1]["error"]["nodeId"] == "template"
    assert state["for_each_result"]["parallel"] is True


def test_parallel_for_each_stream_preserves_child_trace():
    project = create_default_project("Parallel ForEach Stream")
    project.state.fields.extend([StateField(name="items", type="list"), StateField(name="merged_results", type="list"), StateField(name="merge_result", type="dict"), StateField(name="final_answer", type="str")])
    project.nodes.extend(
        [
            NodeIR(id="each", type=NodeType.FOR_EACH, label="ForEach", config={"itemsField": "items", "itemField": "current_item", "indexField": "current_index", "executionMode": "parallel", "maxConcurrency": 2, "preserveOrder": True}),
            NodeIR(id="template", type=NodeType.TEMPLATE, label="Template", config={"template": "{{ state.current_item }}", "outputType": "text", "outputField": "item_result"}),
            NodeIR(id="merge", type=NodeType.MERGE, label="Merge", config={"reducersJson": json.dumps([{"target": "merged_results", "source": "item_result", "reducer": "append"}]), "resultField": "merge_result"}),
            NodeIR(id="reply", type=NodeType.DIRECT_REPLY, label="Reply", config={"template": "{{ state.merged_results }}", "outputField": "final_answer"}),
        ]
    )
    project.edges.extend(
        [
            EdgeIR(id="e1", source="start", target="each"),
            EdgeIR(id="e2", source="each", target="template", sourceHandle="item"),
            EdgeIR(id="e3", source="template", target="merge"),
            EdgeIR(id="e4", source="merge", target="reply"),
        ]
    )

    events = list(preview.iter_project_preview_events(project, {"messages": "run", "items": ["a", "b"]}, "live"))
    run_end = next(event for event in events if event.get("event") == "run_end")
    child_trace = [item for item in run_end["trace"] if item["nodeId"] == "template"]
    merge_trace = [item for item in run_end["trace"] if item["nodeId"] == "merge"]

    assert sorted(item["iterationIndex"] for item in child_trace) == [0, 1]
    assert len(merge_trace) == 1
    assert merge_trace[0]["type"] == "merge"
    assert merge_trace[0]["outputDelta"]["merged_results"] == ["a", "b"]
    assert run_end["outputState"]["merged_results"] == ["a", "b"]
    assert any(item["nodeId"] == "each" and item.get("parallel") is True for item in run_end["trace"])


def test_parallel_for_each_stream_collect_errors_preserves_failed_child_trace():
    project = create_default_project("Parallel ForEach Collect Errors Stream")
    project.state.fields.extend([StateField(name="items", type="list"), StateField(name="merged_results", type="list"), StateField(name="merge_result", type="dict"), StateField(name="final_answer", type="str")])
    project.nodes.extend(
        [
            NodeIR(
                id="each",
                type=NodeType.FOR_EACH,
                label="ForEach",
                config={"itemsField": "items", "itemField": "current_item", "indexField": "current_index", "executionMode": "parallel", "maxConcurrency": 2, "preserveOrder": True, "itemFailurePolicy": "collect_errors"},
            ),
            NodeIR(id="template", type=NodeType.TEMPLATE, label="Template", config={"template": '{"value":"{{ state.current_item }}"}', "outputType": "json", "outputField": "item_result"}),
            NodeIR(id="merge", type=NodeType.MERGE, label="Merge", config={"reducersJson": json.dumps([{"target": "merged_results", "source": "item_result", "reducer": "append"}]), "resultField": "merge_result"}),
            NodeIR(id="reply", type=NodeType.DIRECT_REPLY, label="Reply", config={"template": "{{ state.merged_results }}", "outputField": "final_answer"}),
        ]
    )
    project.edges.extend(
        [
            EdgeIR(id="e1", source="start", target="each"),
            EdgeIR(id="e2", source="each", target="template", sourceHandle="item"),
            EdgeIR(id="e3", source="template", target="merge"),
            EdgeIR(id="e4", source="merge", target="reply"),
        ]
    )

    events = list(preview.iter_project_preview_events(project, {"messages": "run", "items": ["ok", 'bad " json']}, "live"))
    run_end = next(event for event in events if event.get("event") == "run_end")
    stream_child = [event["traceItem"] for event in events if event.get("event") == "node_end" and event.get("traceItem", {}).get("parentNodeId") == "each"]
    final_child = [item for item in run_end["trace"] if item.get("parentNodeId") == "each" and item["nodeId"] == "template"]
    status, pending = run_status_from_state(run_end["trace"], run_end["outputState"])

    stream_child = sorted(stream_child, key=lambda item: int(item["iterationIndex"]))
    final_child = sorted(final_child, key=lambda item: int(item["iterationIndex"]))
    assert [(item["status"], item["iterationIndex"]) for item in stream_child] == [("ok", 0), ("error", 1)]
    assert [(item["status"], item["iterationIndex"]) for item in final_child] == [("ok", 0), ("error", 1)]
    failed_child = final_child[1]
    assert failed_child["nonFatal"] is True
    assert failed_child["handledByParent"] == "for_each_collect_errors"
    assert status == "completed"
    assert pending is None
    assert run_end["outputState"]["merged_results"][0] == {"value": "ok"}
    assert run_end["outputState"]["merged_results"][1]["ok"] is False
    assert run_end["outputState"]["merged_results"][1]["error"]["nodeId"] == "template"


def test_parallel_for_each_stream_fail_fast_preserves_failed_child_trace():
    project = create_default_project("Parallel ForEach Fail Fast Stream")
    project.state.fields.extend([StateField(name="items", type="list"), StateField(name="merged_results", type="list"), StateField(name="merge_result", type="dict")])
    project.nodes.extend(
        [
            NodeIR(id="each", type=NodeType.FOR_EACH, label="ForEach", config={"itemsField": "items", "itemField": "current_item", "indexField": "current_index", "executionMode": "parallel", "maxConcurrency": 2}),
            NodeIR(id="template", type=NodeType.TEMPLATE, label="Template", config={"template": '{"value":"{{ state.current_item }}"}', "outputType": "json", "outputField": "item_result"}),
            NodeIR(id="merge", type=NodeType.MERGE, label="Merge", config={"reducersJson": json.dumps([{"target": "merged_results", "source": "item_result", "reducer": "append"}]), "resultField": "merge_result"}),
        ]
    )
    project.edges.extend(
        [
            EdgeIR(id="e1", source="start", target="each"),
            EdgeIR(id="e2", source="each", target="template", sourceHandle="item"),
            EdgeIR(id="e3", source="template", target="merge"),
        ]
    )

    events = list(preview.iter_project_preview_events(project, {"messages": "run", "items": ["ok", 'bad " json']}, "live"))
    run_end = next(event for event in events if event.get("event") == "run_end")
    stream_child = [event["traceItem"] for event in events if event.get("event") == "node_end" and event.get("traceItem", {}).get("parentNodeId") == "each"]
    final_child = [item for item in run_end["trace"] if item.get("parentNodeId") == "each" and item["nodeId"] == "template"]
    status, pending = run_status_from_state(run_end["trace"], run_end["outputState"])

    assert any(item["status"] == "error" for item in stream_child)
    assert any(item["status"] == "error" for item in final_child)
    assert status == "failed"
    assert pending is None


def test_sequential_for_each_stream_collect_errors_preserves_child_error_payload():
    project = create_default_project("Sequential ForEach Collect Errors Stream")
    project.state.fields.extend([StateField(name="items", type="list"), StateField(name="merged_results", type="list"), StateField(name="merge_result", type="dict")])
    project.nodes.extend(
        [
            NodeIR(id="each", type=NodeType.FOR_EACH, label="ForEach", config={"itemsField": "items", "itemField": "current_item", "indexField": "current_index", "itemFailurePolicy": "collect_errors"}),
            NodeIR(id="template", type=NodeType.TEMPLATE, label="Template", config={"template": '{"value":"{{ state.current_item }}"}', "outputType": "json", "outputField": "item_result"}),
            NodeIR(id="merge", type=NodeType.MERGE, label="Merge", config={"reducersJson": json.dumps([{"target": "merged_results", "source": "item_result", "reducer": "append"}]), "resultField": "merge_result"}),
        ]
    )
    project.edges.extend(
        [
            EdgeIR(id="e1", source="start", target="each"),
            EdgeIR(id="e2", source="each", target="template", sourceHandle="item"),
            EdgeIR(id="e3", source="template", target="merge"),
        ]
    )

    events = list(preview.iter_project_preview_events(project, {"messages": "run", "items": ['bad " json']}, "live"))
    run_end = next(event for event in events if event.get("event") == "run_end")
    final_child = [item for item in run_end["trace"] if item.get("parentNodeId") == "each" and item["nodeId"] == "template"]
    status, pending = run_status_from_state(run_end["trace"], run_end["outputState"])

    assert final_child[0]["status"] == "error"
    assert final_child[0]["nonFatal"] is True
    assert run_end["outputState"]["merged_results"][0]["error"]["nodeId"] == "template"
    assert status == "completed"
    assert pending is None


def test_sequential_for_each_stream_collect_errors_ignores_stale_last_error_before_child_trace():
    project = create_default_project("Sequential ForEach Stale Last Error")
    project.state.fields.extend([StateField(name="items", type="list"), StateField(name="merged_results", type="list"), StateField(name="merge_result", type="dict")])
    project.nodes.extend(
        [
            NodeIR(id="each", type=NodeType.FOR_EACH, label="ForEach", config={"itemsField": "items", "itemField": "current_item", "indexField": "current_index", "itemFailurePolicy": "collect_errors"}),
            NodeIR(id="nested_each", type=NodeType.FOR_EACH, label="Nested ForEach", config={"itemsField": "nested_items"}),
            NodeIR(id="merge", type=NodeType.MERGE, label="Merge", config={"reducersJson": json.dumps([{"target": "merged_results", "source": "item_result", "reducer": "append"}]), "resultField": "merge_result"}),
        ]
    )
    project.edges.extend(
        [
            EdgeIR(id="e1", source="start", target="each"),
            EdgeIR(id="e2", source="each", target="nested_each", sourceHandle="item"),
            EdgeIR(id="e3", source="nested_each", target="merge"),
        ]
    )
    stale_error = {"ok": False, "nodeId": "old_node", "nodeType": "old", "message": "stale"}

    events = list(preview.iter_project_preview_events(project, {"messages": "run", "items": ["a"], "last_error": stale_error}, "live"))
    run_end = next(event for event in events if event.get("event") == "run_end")
    error_payload = run_end["outputState"]["merged_results"][0]["error"]
    status, pending = run_status_from_state(run_end["trace"], run_end["outputState"])

    assert error_payload["nodeId"] == "each"
    assert "ForEach v1 不支持嵌套" in error_payload["message"]
    assert status == "completed"
    assert pending is None


def test_sequential_for_each_stream_collect_errors_isolates_error_payload_per_item():
    project = create_default_project("Sequential ForEach Isolates Item Error Payload")
    project.state.fields.extend([StateField(name="items", type="list"), StateField(name="merged_results", type="list"), StateField(name="merge_result", type="dict")])
    project.nodes.extend(
        [
            NodeIR(id="each", type=NodeType.FOR_EACH, label="ForEach", config={"itemsField": "items", "itemField": "current_item", "indexField": "current_index", "itemFailurePolicy": "collect_errors"}),
            NodeIR(id="route", type=NodeType.CONDITION, label="Route", config={"field": "current_item", "operator": "contains", "value": "bad", "trueBranch": "bad", "falseBranch": "nested"}),
            NodeIR(id="bad_template", type=NodeType.TEMPLATE, label="Bad Template", config={"template": '{"value":"{{ state.current_item }}"}', "outputType": "json", "outputField": "item_result"}),
            NodeIR(id="nested_each", type=NodeType.FOR_EACH, label="Nested ForEach", config={"itemsField": "nested_items"}),
            NodeIR(id="merge", type=NodeType.MERGE, label="Merge", config={"reducersJson": json.dumps([{"target": "merged_results", "source": "item_result", "reducer": "append"}]), "resultField": "merge_result"}),
        ]
    )
    project.edges.extend(
        [
            EdgeIR(id="e1", source="start", target="each"),
            EdgeIR(id="e2", source="each", target="route", sourceHandle="item"),
            EdgeIR(id="e3", source="route", target="bad_template", kind=EdgeKind.CONDITIONAL, sourceHandle="bad"),
            EdgeIR(id="e4", source="route", target="nested_each", kind=EdgeKind.CONDITIONAL, sourceHandle="nested"),
            EdgeIR(id="e5", source="bad_template", target="merge"),
            EdgeIR(id="e6", source="nested_each", target="merge"),
        ]
    )

    events = list(preview.iter_project_preview_events(project, {"messages": "run", "items": ['bad " json', "nested"]}, "live"))
    run_end = next(event for event in events if event.get("event") == "run_end")
    errors = [item["error"] for item in run_end["outputState"]["merged_results"]]
    status, pending = run_status_from_state(run_end["trace"], run_end["outputState"])

    assert errors[0]["nodeId"] == "bad_template"
    assert errors[1]["nodeId"] == "each"
    assert "ForEach v1 不支持嵌套" in errors[1]["message"]
    assert status == "completed"
    assert pending is None


def test_parallel_for_each_stream_collect_errors_ignores_stale_last_error_before_child_trace():
    project = create_default_project("Parallel ForEach Stale Last Error")
    project.state.fields.extend([StateField(name="items", type="list"), StateField(name="merged_results", type="list"), StateField(name="merge_result", type="dict")])
    project.nodes.extend(
        [
            NodeIR(id="each", type=NodeType.FOR_EACH, label="ForEach", config={"itemsField": "items", "itemField": "current_item", "indexField": "current_index", "executionMode": "parallel", "maxConcurrency": 2, "preserveOrder": True, "itemFailurePolicy": "collect_errors"}),
            NodeIR(id="nested_each", type=NodeType.FOR_EACH, label="Nested ForEach", config={"itemsField": "nested_items"}),
            NodeIR(id="merge", type=NodeType.MERGE, label="Merge", config={"reducersJson": json.dumps([{"target": "merged_results", "source": "item_result", "reducer": "append"}]), "resultField": "merge_result"}),
        ]
    )
    project.edges.extend(
        [
            EdgeIR(id="e1", source="start", target="each"),
            EdgeIR(id="e2", source="each", target="nested_each", sourceHandle="item"),
            EdgeIR(id="e3", source="nested_each", target="merge"),
        ]
    )
    stale_error = {"ok": False, "nodeId": "old_node", "nodeType": "old", "message": "stale"}

    events = list(preview.iter_project_preview_events(project, {"messages": "run", "items": ["a", "b"], "last_error": stale_error}, "live"))
    run_end = next(event for event in events if event.get("event") == "run_end")
    errors = [item["error"] for item in run_end["outputState"]["merged_results"]]
    status, pending = run_status_from_state(run_end["trace"], run_end["outputState"])

    assert [error["nodeId"] for error in errors] == ["each", "each"]
    assert all("ForEach v1 不支持嵌套" in error["message"] for error in errors)
    assert status == "completed"
    assert pending is None


def test_sequential_for_each_stream_fail_fast_preserves_failed_child_trace():
    project = create_default_project("Sequential ForEach Fail Fast Stream")
    project.state.fields.extend([StateField(name="items", type="list"), StateField(name="merged_results", type="list"), StateField(name="merge_result", type="dict")])
    project.nodes.extend(
        [
            NodeIR(id="each", type=NodeType.FOR_EACH, label="ForEach", config={"itemsField": "items", "itemField": "current_item", "indexField": "current_index"}),
            NodeIR(id="template", type=NodeType.TEMPLATE, label="Template", config={"template": '{"value":"{{ state.current_item }}"}', "outputType": "json", "outputField": "item_result"}),
            NodeIR(id="merge", type=NodeType.MERGE, label="Merge", config={"reducersJson": json.dumps([{"target": "merged_results", "source": "item_result", "reducer": "append"}]), "resultField": "merge_result"}),
        ]
    )
    project.edges.extend(
        [
            EdgeIR(id="e1", source="start", target="each"),
            EdgeIR(id="e2", source="each", target="template", sourceHandle="item"),
            EdgeIR(id="e3", source="template", target="merge"),
        ]
    )

    events = list(preview.iter_project_preview_events(project, {"messages": "run", "items": ['bad " json']}, "live"))
    run_end = next(event for event in events if event.get("event") == "run_end")
    stream_child = [event["traceItem"] for event in events if event.get("event") == "node_end" and event.get("traceItem", {}).get("parentNodeId") == "each"]
    final_child = [item for item in run_end["trace"] if item.get("parentNodeId") == "each" and item["nodeId"] == "template"]
    status, pending = run_status_from_state(run_end["trace"], run_end["outputState"])

    assert any(item["status"] == "error" for item in stream_child)
    assert any(item["status"] == "error" for item in final_child)
    assert status == "failed"
    assert pending is None


def test_sequential_for_each_stream_missing_merge_preserves_child_trace():
    project = create_default_project("Sequential ForEach Missing Merge Stream")
    project.state.fields.extend([StateField(name="items", type="list"), StateField(name="merged_results", type="list"), StateField(name="merge_result", type="dict"), StateField(name="item_result", type="str")])
    project.nodes.extend(
        [
            NodeIR(id="each", type=NodeType.FOR_EACH, label="ForEach", config={"itemsField": "items", "itemField": "current_item", "indexField": "current_index"}),
            NodeIR(id="reply_item", type=NodeType.DIRECT_REPLY, label="Reply Item", config={"template": "{{ state.current_item }}", "outputField": "item_result"}),
            NodeIR(id="merge", type=NodeType.MERGE, label="Merge", config={"reducersJson": json.dumps([{"target": "merged_results", "source": "item_result", "reducer": "append"}]), "resultField": "merge_result"}),
        ]
    )
    project.edges.extend(
        [
            EdgeIR(id="e1", source="start", target="each"),
            EdgeIR(id="e2", source="each", target="reply_item", sourceHandle="item"),
            EdgeIR(id="e3", source="reply_item", target="merge"),
        ]
    )

    events = list(preview.iter_project_preview_events(project, {"messages": "run", "items": ["a"]}, "live"))
    run_end = next(event for event in events if event.get("event") == "run_end")
    stream_child = [event["traceItem"] for event in events if event.get("event") == "node_end" and event.get("traceItem", {}).get("parentNodeId") == "each"]
    final_child = [item for item in run_end["trace"] if item.get("parentNodeId") == "each" and item["nodeId"] == "reply_item"]
    status, pending = run_status_from_state(run_end["trace"], run_end["outputState"])

    assert [item["nodeId"] for item in stream_child] == ["reply_item"]
    assert [item["nodeId"] for item in final_child] == ["reply_item"]
    assert status == "failed"
    assert pending is None


def test_parallel_for_each_stream_missing_merge_preserves_child_trace():
    project = create_default_project("Parallel ForEach Missing Merge Stream")
    project.state.fields.extend([StateField(name="items", type="list"), StateField(name="merged_results", type="list"), StateField(name="merge_result", type="dict"), StateField(name="item_result", type="str")])
    project.nodes.extend(
        [
            NodeIR(id="each", type=NodeType.FOR_EACH, label="ForEach", config={"itemsField": "items", "itemField": "current_item", "indexField": "current_index", "executionMode": "parallel", "maxConcurrency": 2, "preserveOrder": True}),
            NodeIR(id="reply_item", type=NodeType.DIRECT_REPLY, label="Reply Item", config={"template": "{{ state.current_item }}", "outputField": "item_result"}),
            NodeIR(id="merge", type=NodeType.MERGE, label="Merge", config={"reducersJson": json.dumps([{"target": "merged_results", "source": "item_result", "reducer": "append"}]), "resultField": "merge_result"}),
        ]
    )
    project.edges.extend(
        [
            EdgeIR(id="e1", source="start", target="each"),
            EdgeIR(id="e2", source="each", target="reply_item", sourceHandle="item"),
            EdgeIR(id="e3", source="reply_item", target="merge"),
        ]
    )

    events = list(preview.iter_project_preview_events(project, {"messages": "run", "items": ["a", "b"]}, "live"))
    run_end = next(event for event in events if event.get("event") == "run_end")
    stream_child = [event["traceItem"] for event in events if event.get("event") == "node_end" and event.get("traceItem", {}).get("parentNodeId") == "each"]
    final_child = [item for item in run_end["trace"] if item.get("parentNodeId") == "each" and item["nodeId"] == "reply_item"]
    status, pending = run_status_from_state(run_end["trace"], run_end["outputState"])

    assert sorted(item["iterationIndex"] for item in stream_child) == [0, 1]
    assert sorted(item["iterationIndex"] for item in final_child) == [0, 1]
    assert status == "failed"
    assert pending is None


def test_for_each_collect_errors_missing_merge_live_preview_continues():
    project = create_default_project("ForEach Collect Missing Merge Live")
    project.state.fields.extend([StateField(name="items", type="list"), StateField(name="merged_results", type="list"), StateField(name="merge_result", type="dict"), StateField(name="item_result", type="str")])
    project.nodes.extend(
        [
            NodeIR(id="each", type=NodeType.FOR_EACH, label="ForEach", config={"itemsField": "items", "itemField": "current_item", "indexField": "current_index", "itemFailurePolicy": "collect_errors"}),
            NodeIR(id="reply_item", type=NodeType.DIRECT_REPLY, label="Reply Item", config={"template": "{{ state.current_item }}", "outputField": "item_result"}),
            NodeIR(id="merge", type=NodeType.MERGE, label="Merge", config={"reducersJson": json.dumps([{"target": "merged_results", "source": "item_result", "reducer": "append"}]), "resultField": "merge_result"}),
        ]
    )
    project.edges.extend(
        [
            EdgeIR(id="e1", source="start", target="each"),
            EdgeIR(id="e2", source="each", target="reply_item", sourceHandle="item"),
            EdgeIR(id="e3", source="reply_item", target="merge"),
        ]
    )

    trace, state = preview.run_project_preview(project, {"messages": "run", "items": ["a"]}, "live")
    status, pending = run_status_from_state(trace, state)

    assert state["merged_results"][0]["ok"] is False
    assert state["merged_results"][0]["error"]["nodeId"] == "each"
    assert "没有到达 Merge" in state["merged_results"][0]["error"]["message"]
    assert status == "completed"
    assert pending is None


def test_sequential_for_each_stream_collect_errors_missing_merge_continues():
    project = create_default_project("Sequential ForEach Collect Missing Merge Stream")
    project.state.fields.extend([StateField(name="items", type="list"), StateField(name="merged_results", type="list"), StateField(name="merge_result", type="dict"), StateField(name="item_result", type="str")])
    project.nodes.extend(
        [
            NodeIR(id="each", type=NodeType.FOR_EACH, label="ForEach", config={"itemsField": "items", "itemField": "current_item", "indexField": "current_index", "itemFailurePolicy": "collect_errors"}),
            NodeIR(id="reply_item", type=NodeType.DIRECT_REPLY, label="Reply Item", config={"template": "{{ state.current_item }}", "outputField": "item_result"}),
            NodeIR(id="merge", type=NodeType.MERGE, label="Merge", config={"reducersJson": json.dumps([{"target": "merged_results", "source": "item_result", "reducer": "append"}]), "resultField": "merge_result"}),
        ]
    )
    project.edges.extend(
        [
            EdgeIR(id="e1", source="start", target="each"),
            EdgeIR(id="e2", source="each", target="reply_item", sourceHandle="item"),
            EdgeIR(id="e3", source="reply_item", target="merge"),
        ]
    )

    events = list(preview.iter_project_preview_events(project, {"messages": "run", "items": ["a"]}, "live"))
    run_end = next(event for event in events if event.get("event") == "run_end")
    status, pending = run_status_from_state(run_end["trace"], run_end["outputState"])

    assert run_end["outputState"]["merged_results"][0]["ok"] is False
    assert run_end["outputState"]["merged_results"][0]["error"]["nodeId"] == "each"
    assert status == "completed"
    assert pending is None


def test_parallel_for_each_stream_collect_errors_missing_merge_continues():
    project = create_default_project("Parallel ForEach Collect Missing Merge Stream")
    project.state.fields.extend([StateField(name="items", type="list"), StateField(name="merged_results", type="list"), StateField(name="merge_result", type="dict"), StateField(name="item_result", type="str")])
    project.nodes.extend(
        [
            NodeIR(id="each", type=NodeType.FOR_EACH, label="ForEach", config={"itemsField": "items", "itemField": "current_item", "indexField": "current_index", "executionMode": "parallel", "maxConcurrency": 2, "preserveOrder": True, "itemFailurePolicy": "collect_errors"}),
            NodeIR(id="reply_item", type=NodeType.DIRECT_REPLY, label="Reply Item", config={"template": "{{ state.current_item }}", "outputField": "item_result"}),
            NodeIR(id="merge", type=NodeType.MERGE, label="Merge", config={"reducersJson": json.dumps([{"target": "merged_results", "source": "item_result", "reducer": "append"}]), "resultField": "merge_result"}),
        ]
    )
    project.edges.extend(
        [
            EdgeIR(id="e1", source="start", target="each"),
            EdgeIR(id="e2", source="each", target="reply_item", sourceHandle="item"),
            EdgeIR(id="e3", source="reply_item", target="merge"),
        ]
    )

    events = list(preview.iter_project_preview_events(project, {"messages": "run", "items": ["a", "b"]}, "live"))
    run_end = next(event for event in events if event.get("event") == "run_end")
    status, pending = run_status_from_state(run_end["trace"], run_end["outputState"])

    assert [item["ok"] for item in run_end["outputState"]["merged_results"]] == [False, False]
    assert [item["error"]["nodeId"] for item in run_end["outputState"]["merged_results"]] == ["each", "each"]
    assert status == "completed"
    assert pending is None


def test_stream_for_each_error_branch_child_trace_is_handled():
    project = create_default_project("ForEach Error Branch")
    project.state.fields.extend([StateField(name="items", type="list"), StateField(name="merged_results", type="list"), StateField(name="merge_result", type="dict"), StateField(name="final_answer", type="str")])
    project.nodes.extend(
        [
            NodeIR(id="each", type=NodeType.FOR_EACH, label="ForEach", config={"itemsField": "items", "itemField": "current_item", "indexField": "current_index"}),
            NodeIR(id="bad_template", type=NodeType.TEMPLATE, label="Bad Template", config={"template": "{bad json", "outputType": "json", "outputField": "item_result"}),
            NodeIR(id="recover", type=NodeType.TEMPLATE, label="Recover", config={"template": '{"ok":false,"handled":"{{ state.last_error.nodeId }}"}', "outputType": "json", "outputField": "item_result"}),
            NodeIR(id="merge", type=NodeType.MERGE, label="Merge", config={"reducersJson": json.dumps([{"target": "merged_results", "source": "item_result", "reducer": "append"}]), "resultField": "merge_result"}),
            NodeIR(id="reply", type=NodeType.DIRECT_REPLY, label="Reply", config={"template": "{{ state.merged_results }}", "outputField": "final_answer"}),
        ]
    )
    project.edges.extend(
        [
            EdgeIR(id="e1", source="start", target="each"),
            EdgeIR(id="e2", source="each", target="bad_template", sourceHandle="item"),
            EdgeIR(id="e3", source="bad_template", target="recover", kind=EdgeKind.ERROR, sourceHandle="error"),
            EdgeIR(id="e4", source="recover", target="merge"),
            EdgeIR(id="e5", source="merge", target="reply"),
        ]
    )

    events = list(preview.iter_project_preview_events(project, {"messages": "run", "items": ["a"]}, "live"))
    run_end = next(event for event in events if event.get("event") == "run_end")
    bad_trace = next(item for item in run_end["trace"] if item["nodeId"] == "bad_template")
    status, pending = run_status_from_state(run_end["trace"], run_end["outputState"])

    assert status == "completed"
    assert pending is None
    assert bad_trace["status"] == "ok"
    assert bad_trace["handledError"] is True
    assert bad_trace["errorTarget"] == "recover"
    assert run_end["outputState"]["merged_results"] == [{"ok": False, "handled": "bad_template"}]


def test_stream_for_each_parent_timeout_fallback_continues(monkeypatch):
    project = create_default_project("Stream ForEach Timeout")
    project.state.fields.extend(
        [
            StateField(name="items", type="list"),
            StateField(name="item_result", type="dict"),
            StateField(name="merged_results", type="list"),
            StateField(name="merge_result", type="dict"),
            StateField(name="fallback_result", type="str"),
            StateField(name="node_error", type="dict"),
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
                    "nodeTimeoutSec": 0.01,
                    "errorPolicy": "fallback",
                    "fallbackOutputJson": json.dumps({"fallback_result": "foreach timeout"}),
                    "errorOutputField": "node_error",
                },
            ),
            NodeIR(id="slow_http", type=NodeType.HTTP, label="Slow HTTP", config={"method": "GET", "url": "https://example.com/slow", "mockResponseJson": "", "outputField": "item_result"}),
            NodeIR(id="merge", type=NodeType.MERGE, label="Merge", config={"reducersJson": json.dumps([{"target": "merged_results", "source": "item_result", "reducer": "append"}]), "resultField": "merge_result"}),
            NodeIR(id="reply", type=NodeType.DIRECT_REPLY, label="Reply", config={"template": "{{ state.fallback_result }}", "outputField": "final_answer"}),
        ]
    )
    project.edges.extend(
        [
            EdgeIR(id="e1", source="start", target="each"),
            EdgeIR(id="e2", source="each", target="slow_http", sourceHandle="item"),
            EdgeIR(id="e3", source="slow_http", target="merge"),
            EdgeIR(id="e4", source="merge", target="reply"),
        ]
    )

    class FakeHttpResponse:
        text = ""

        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": True}

    def fake_request(*_args, **_kwargs):
        import time

        time.sleep(0.05)
        return FakeHttpResponse()

    monkeypatch.setattr(http_node.httpx, "request", fake_request)

    events = list(preview.iter_project_preview_events(project, {"messages": "run", "items": ["a"]}, "live"))
    run_end = next(event for event in events if event.get("event") == "run_end")
    each_trace = next(item for item in run_end["trace"] if item["nodeId"] == "each")

    assert any(event.get("event") == "node_start" and event.get("nodeId") == "slow_http" for event in events)
    assert each_trace["status"] == "ok"
    assert each_trace["errorPolicy"] == "fallback"
    assert each_trace["timeoutSec"] == 0.01
    assert each_trace["attempts"][0]["errorType"] == "timeout"
    assert run_end["outputState"]["fallback_result"] == "foreach timeout"
    assert run_end["outputState"]["node_error"]["errorType"] == "timeout"
    assert run_end["outputState"]["final_answer"] == "foreach timeout"


def test_branch_merge_merges_current_branch_state():
    project = create_default_project("Branch Merge")
    project.state.fields.extend(
        [
            StateField(name="route", type="str"),
            StateField(name="branch_result", type="str"),
            StateField(name="merged_branch", type="str"),
            StateField(name="merge_result", type="dict"),
            StateField(name="final_answer", type="str"),
        ]
    )
    project.nodes.extend(
        [
            NodeIR(id="condition", type=NodeType.CONDITION, label="Condition", config={"field": "route", "operator": "equals", "value": "a", "trueBranch": "true", "falseBranch": "false", "fallback": "false"}),
            NodeIR(id="branch_a", type=NodeType.TEMPLATE, label="Branch A", config={"template": "A", "outputType": "text", "outputField": "branch_result"}),
            NodeIR(id="branch_b", type=NodeType.TEMPLATE, label="Branch B", config={"template": "B", "outputType": "text", "outputField": "branch_result"}),
            NodeIR(id="merge", type=NodeType.MERGE, label="Branch Merge", config={"mergeMode": "branch", "reducersJson": json.dumps([{"target": "merged_branch", "source": "branch_result", "reducer": "overwrite"}]), "resultField": "merge_result"}),
            NodeIR(id="reply", type=NodeType.DIRECT_REPLY, label="Reply", config={"template": "{{ state.merged_branch }}", "outputField": "final_answer"}),
        ]
    )
    project.edges.extend(
        [
            EdgeIR(id="e1", source="start", target="condition"),
            EdgeIR(id="e2", source="condition", target="branch_a", kind=EdgeKind.CONDITIONAL, sourceHandle="true"),
            EdgeIR(id="e3", source="condition", target="branch_b", kind=EdgeKind.CONDITIONAL, sourceHandle="false"),
            EdgeIR(id="e4", source="branch_a", target="merge"),
            EdgeIR(id="e5", source="branch_b", target="merge"),
            EdgeIR(id="e6", source="merge", target="reply"),
        ]
    )

    _trace, state = preview.run_project_preview(project, {"messages": "run", "route": "b"}, "live")

    assert state["merged_branch"] == "B"
    assert state["merge_result"]["mergeMode"] == "branch"
    assert state["final_answer"] == "B"


def test_builtin_read_file_respects_runtime_allowed_roots(tmp_path: Path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    inside = allowed / "note.txt"
    inside.write_text("允许读取", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("禁止读取", encoding="utf-8")
    tool_config = {
        "id": "builtin_read_file",
        "name": "read_file",
        "source": "builtin",
        "schemaJson": json.dumps({"type": "object", "x-graphic": {"kind": "builtin_tool", "builtinId": "read_file"}}),
    }
    runtime = {
        "allowedRootsJson": json.dumps([str(allowed)]),
        "networkEnabled": True,
        "allowedHostsJson": "[]",
        "maxFileBytes": 1024,
        "maxHttpBytes": 1024,
    }

    ok = tool_runtime_registry.invoke_registered_tool(tool_config, {"path": str(inside)}, runtime)
    relative_ok = tool_runtime_registry.invoke_registered_tool(tool_config, {"path": "note.txt"}, runtime)
    blocked = tool_runtime_registry.invoke_registered_tool(tool_config, {"path": str(outside)}, runtime)
    list_config = {
        "id": "builtin_list_directory",
        "name": "list_directory",
        "source": "builtin",
        "schemaJson": json.dumps({"type": "object", "x-graphic": {"kind": "builtin_tool", "builtinId": "list_directory"}}),
    }
    listed = tool_runtime_registry.invoke_registered_tool(list_config, {"path": "."}, runtime)

    assert ok["ok"] is True
    assert ok["result"]["content"] == "允许读取"
    assert relative_ok["ok"] is True
    assert relative_ok["result"]["path"] == str(inside.resolve())
    assert listed["ok"] is True
    assert listed["result"]["path"] == str(allowed.resolve())
    assert listed["result"]["entries"][0]["name"] == "note.txt"
    assert blocked["ok"] is False
    assert "允许目录" in blocked["error"]


def test_tools_agent_can_call_builtin_read_file(monkeypatch, tmp_path: Path):
    docs = tmp_path / "docs"
    docs.mkdir()
    target = docs / "faq.txt"
    target.write_text("FAQ 内容", encoding="utf-8")
    seen_messages = []

    def fake_call_chat_model(provider, model, messages, runtime_config=None):
        seen_messages.append(messages)
        if len(seen_messages) == 1:
            return FakeResponse(json.dumps({"tool_calls": [{"tool": "read_file", "args": {"path": str(target)}}], "final_answer": ""}))
        return FakeResponse(json.dumps({"tool_calls": [], "final_answer": "读取完成"}))

    monkeypatch.setattr(model_runtime, "call_chat_model", fake_call_chat_model)
    project = create_default_project("内置工具测试")
    project.state.fields.extend(
        [
            StateField(name="tools_result", type="str"),
            StateField(name="tools_result_tool_calls", type="list"),
            StateField(name="final_answer", type="str"),
        ]
    )
    schema = {"type": "object", "x-graphic": {"kind": "builtin_tool", "builtinId": "read_file"}}
    project.tools.append(ToolConfig(id="builtin_read_file", name="read_file", description="读取文件", source="builtin", schemaJson=json.dumps(schema)))
    project.nodes.append(
        NodeIR(
            id="tools_agent",
            type=NodeType.TOOL,
            label="Tools",
            config={"toolIdsJson": '["builtin_read_file"]', "outputField": "tools_result"},
        )
    )
    project.edges.append(EdgeIR(id="e1", source="start", target="tools_agent"))
    runtime = {
        "allowedRootsJson": json.dumps([str(docs)]),
        "networkEnabled": True,
        "allowedHostsJson": "[]",
        "maxFileBytes": 1024,
        "maxHttpBytes": 1024,
    }

    trace, state = preview.run_project_preview(project, {"messages": "读取文件"}, "live", None, runtime)

    assert trace[0]["status"] == "ok"
    assert state["tools_result"] == "读取完成"
    assert state["tools_result_tool_calls"][0]["observation"]["result"]["content"] == "FAQ 内容"


def test_agent_can_call_selected_builtin_tool(monkeypatch, tmp_path: Path):
    docs = tmp_path / "repo"
    docs.mkdir()
    target = docs / "README.md"
    target.write_text("项目验收说明", encoding="utf-8")
    seen_messages = []

    def fake_call_chat_model(provider, model, messages, runtime_config=None):
        seen_messages.append(messages)
        if len(seen_messages) == 1:
            return FakeResponse(json.dumps({"tool_calls": [{"tool": "read_file", "args": {"path": "README.md"}}], "final_answer": ""}, ensure_ascii=False))
        return FakeResponse(json.dumps({"tool_calls": [], "final_answer": "已读取项目验收说明"}, ensure_ascii=False))

    monkeypatch.setattr(model_runtime, "call_chat_model", fake_call_chat_model)
    project = create_default_project("Agent 本地工具")
    project.state.fields.extend(
        [
            StateField(name="agent_result", type="str"),
            StateField(name="agent_result_tool_calls", type="list"),
            StateField(name="agent_result_mcp_tool_calls", type="list"),
            StateField(name="agent_result_agent_tool_calls", type="list"),
        ]
    )
    schema = {"type": "object", "x-graphic": {"kind": "builtin_tool", "builtinId": "read_file"}}
    project.tools.append(ToolConfig(id="builtin_read_file", name="read_file", description="读取文件", source="builtin", schemaJson=json.dumps(schema)))
    project.nodes.append(
        NodeIR(
            id="agent",
            type=NodeType.AGENT,
            label="Agent",
            config={"toolIdsJson": '["builtin_read_file"]', "outputField": "agent_result", "maxIterations": 2},
        )
    )
    project.edges.append(EdgeIR(id="e1", source="start", target="agent"))
    runtime = {
        "allowedRootsJson": json.dumps([str(docs)]),
        "networkEnabled": True,
        "allowedHostsJson": "[]",
        "maxFileBytes": 1024,
        "maxHttpBytes": 1024,
    }

    trace, state = preview.run_project_preview(project, {"messages": "读取说明"}, "live", None, runtime)

    assert trace[0]["status"] == "ok"
    assert state["agent_result"] == "已读取项目验收说明"
    assert state["agent_result_tool_calls"][0]["tool"] == "read_file"
    assert state["agent_result_tool_calls"][0]["observation"]["result"]["content"] == "项目验收说明"
    assert state["agent_result_mcp_tool_calls"] == []
    assert state["agent_result_agent_tool_calls"] == []
    assert "可用工具" in seen_messages[0][0][1]


def test_for_each_agent_worker_calls_builtin_tool_and_merges(monkeypatch, tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    target = repo / "README.md"
    target.write_text("真实 Worker 证据", encoding="utf-8")
    seen_messages = []

    def fake_call_chat_model(provider, model, messages, runtime_config=None):
        seen_messages.append(messages)
        if len(seen_messages) % 2 == 1:
            return FakeResponse(json.dumps({"tool_calls": [{"tool": "read_file", "args": {"path": "README.md"}}], "final_answer": ""}, ensure_ascii=False))
        return FakeResponse(json.dumps({"tool_calls": [], "final_answer": f"任务 {len(seen_messages) // 2} 已真实检查"}, ensure_ascii=False))

    monkeypatch.setattr(model_runtime, "call_chat_model", fake_call_chat_model)
    project = create_default_project("ForEach Agent Worker")
    project.state.fields.extend(
        [
            StateField(name="items", type="list"),
            StateField(name="item_result", type="str"),
            StateField(name="merged_results", type="list"),
            StateField(name="merge_result", type="dict"),
            StateField(name="final_answer", type="str"),
        ]
    )
    schema = {"type": "object", "x-graphic": {"kind": "builtin_tool", "builtinId": "read_file"}}
    project.tools.append(ToolConfig(id="builtin_read_file", name="read_file", description="读取文件", source="builtin", schemaJson=json.dumps(schema)))
    project.nodes.extend(
        [
            NodeIR(id="each", type=NodeType.FOR_EACH, label="ForEach", config={"itemsField": "items", "itemField": "current_item", "indexField": "current_index"}),
            NodeIR(
                id="worker",
                type=NodeType.AGENT,
                label="Worker",
                config={
                    "systemPrompt": "你是真实 Worker，必须调用工具。",
                    "userPrompt": "任务：{{ state.current_item.goal }}",
                    "toolIdsJson": '["builtin_read_file"]',
                    "outputField": "item_result",
                    "maxIterations": 2,
                },
            ),
            NodeIR(id="merge", type=NodeType.MERGE, label="Merge", config={"reducersJson": json.dumps([{"target": "merged_results", "source": "item_result", "reducer": "append"}]), "resultField": "merge_result"}),
            NodeIR(id="reply", type=NodeType.DIRECT_REPLY, label="Reply", config={"template": "{{ state.merged_results }}", "outputField": "final_answer"}),
        ]
    )
    project.edges.extend(
        [
            EdgeIR(id="e1", source="start", target="each"),
            EdgeIR(id="e2", source="each", target="worker", sourceHandle="item"),
            EdgeIR(id="e3", source="worker", target="merge"),
            EdgeIR(id="e4", source="merge", target="reply"),
        ]
    )
    runtime = {
        "allowedRootsJson": json.dumps([str(repo)]),
        "networkEnabled": True,
        "allowedHostsJson": "[]",
        "maxFileBytes": 1024,
        "maxHttpBytes": 1024,
    }

    events = list(preview.iter_project_preview_events(project, {"messages": "验收", "items": [{"goal": "检查 A"}, {"goal": "检查 B"}]}, "live", None, runtime))
    run_end = next(event for event in events if event.get("event") == "run_end")
    worker_trace = [item for item in run_end["trace"] if item["nodeId"] == "worker"]

    assert sorted(item["iterationIndex"] for item in worker_trace) == [0, 1]
    assert run_end["outputState"]["merged_results"] == ["任务 1 已真实检查", "任务 2 已真实检查"]
    assert all(item["outputDelta"]["item_result_tool_calls"][0]["tool"] == "read_file" for item in worker_trace)


def test_tools_agent_summarizes_after_last_tool_iteration(monkeypatch, tmp_path: Path):
    docs = tmp_path / "docs"
    docs.mkdir()
    target = docs / "faq.txt"
    target.write_text("HTML 样式内容", encoding="utf-8")
    seen_messages = []

    def fake_call_chat_model(provider, model, messages, runtime_config=None):
        seen_messages.append(messages)
        if len(seen_messages) == 1:
            return FakeResponse(json.dumps({"tool_calls": [{"tool": "read_file", "args": {"path": "faq.txt", "max_chars": 10000}}], "final_answer": ""}))
        assert "HTML 样式内容" in json.dumps(messages, ensure_ascii=False)
        return FakeResponse(json.dumps({"tool_calls": [], "final_answer": "已读取 HTML 样式内容"}))

    monkeypatch.setattr(model_runtime, "call_chat_model", fake_call_chat_model)
    project = create_default_project("最终总结测试")
    project.state.fields.extend([StateField(name="tools_result", type="str"), StateField(name="tools_result_tool_calls", type="list")])
    schema = {"type": "object", "x-graphic": {"kind": "builtin_tool", "builtinId": "read_file"}}
    project.tools.append(ToolConfig(id="builtin_read_file", name="read_file", description="读取文件", source="builtin", schemaJson=json.dumps(schema)))
    project.nodes.append(
        NodeIR(
            id="tools_agent",
            type=NodeType.TOOL,
            label="Tools",
            config={"toolIdsJson": '["builtin_read_file"]', "outputField": "tools_result", "maxIterations": 1},
        )
    )
    project.nodes.append(
        NodeIR(
            id="reply",
            type=NodeType.DIRECT_REPLY,
            label="回复",
            config={"outputField": "final_answer"},
        )
    )
    project.edges.append(EdgeIR(id="e1", source="start", target="tools_agent"))
    project.edges.append(EdgeIR(id="e2", source="tools_agent", target="reply"))
    runtime = {
        "allowedRootsJson": json.dumps([str(docs)]),
        "networkEnabled": True,
        "allowedHostsJson": "[]",
        "maxFileBytes": 1024,
        "maxHttpBytes": 1024,
    }

    trace, state = preview.run_project_preview(project, {"messages": "读取 html"}, "live", None, runtime)

    assert trace[0]["status"] == "ok"
    assert trace[1]["status"] == "ok"
    assert state["tools_result"] == "已读取 HTML 样式内容"
    assert state["final_answer"] == "已读取 HTML 样式内容"
    assert state["tools_result_tool_calls"][0]["observation"]["result"]["path"] == str(target.resolve())
    assert len(seen_messages) == 2


def test_builtin_read_file_chunk_supports_lines_offsets_and_allowed_roots(tmp_path: Path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    target = allowed / "app.py"
    target.write_bytes("line1\nline2 target\nline3\nline4\n".encode("utf-8"))
    outside = tmp_path / "outside.py"
    outside.write_text("secret", encoding="utf-8")
    tool_config = {
        "id": "builtin_read_file_chunk",
        "name": "read_file_chunk",
        "source": "builtin",
        "schemaJson": json.dumps({"type": "object", "x-graphic": {"kind": "builtin_tool", "builtinId": "read_file_chunk"}}),
    }
    runtime = {
        "allowedRootsJson": json.dumps([str(allowed)]),
        "networkEnabled": True,
        "allowedHostsJson": "[]",
        "maxFileBytes": 1024,
        "maxHttpBytes": 1024,
    }

    by_line = tool_runtime_registry.invoke_registered_tool(tool_config, {"path": "app.py", "start_line": 2, "end_line": 3}, runtime)
    by_offset = tool_runtime_registry.invoke_registered_tool(tool_config, {"path": "app.py", "offset": 0, "max_chars": 5}, runtime)
    blocked = tool_runtime_registry.invoke_registered_tool(tool_config, {"path": str(outside), "start_line": 1}, runtime)

    assert by_line["ok"] is True
    assert by_line["result"]["content"] == "line2 target\nline3\n"
    assert by_line["result"]["totalLines"] == 4
    assert by_line["result"]["nextStartLine"] == 4
    assert by_offset["ok"] is True
    assert by_offset["result"]["content"] == "line1"
    assert by_offset["result"]["nextOffset"] == 5
    assert by_offset["result"]["truncated"] is True
    assert blocked["ok"] is False
    assert "允许目录" in blocked["error"]


def test_builtin_search_code_supports_text_regex_glob_context_and_skips_binary(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    src = root / "src"
    src.mkdir()
    (src / "app.py").write_text("alpha\nneedle = 1\nomega\n", encoding="utf-8")
    (src / "app.txt").write_text("needle in txt\n", encoding="utf-8")
    (src / "data.bin").write_bytes(b"\x00needle")
    excluded = root / "node_modules"
    excluded.mkdir()
    (excluded / "pkg.py").write_text("needle\n", encoding="utf-8")
    tool_config = {
        "id": "builtin_search_code",
        "name": "search_code",
        "source": "builtin",
        "schemaJson": json.dumps({"type": "object", "x-graphic": {"kind": "builtin_tool", "builtinId": "search_code"}}),
    }
    runtime = {
        "allowedRootsJson": json.dumps([str(root)]),
        "networkEnabled": True,
        "allowedHostsJson": "[]",
        "maxFileBytes": 1024,
        "maxHttpBytes": 1024,
    }

    result = tool_runtime_registry.invoke_registered_tool(
        tool_config,
        {"root": ".", "query": r"needle", "regex": True, "file_glob": "*", "context_lines": 1},
        runtime,
    )

    assert result["ok"] is True
    assert len(result["result"]["matches"]) == 2
    match = result["result"]["matches"][0]
    assert match["relativePath"] == "src/app.py"
    assert match["line"] == 2
    assert match["before"] == ["alpha"]
    assert match["after"] == ["omega"]
    assert {item["relativePath"] for item in result["result"]["matches"]} == {"src/app.py", "src/app.txt"}
    assert result["result"]["skippedBinaryFiles"] == 1


def test_builtin_list_code_symbols_supports_python_html_js_css(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    py_file = root / "module.py"
    py_file.write_text("class Service:\n    def run(self):\n        pass\n\ndef helper():\n    return 1\n", encoding="utf-8")
    html_file = root / "index.html"
    html_file.write_text('<main id="app"><section class="hero primary">Hi</section></main>', encoding="utf-8")
    js_file = root / "app.tsx"
    js_file.write_text("export function View() { return null }\nconst Card = () => null\nclass Store {}\n", encoding="utf-8")
    css_file = root / "style.css"
    css_file.write_text(".hero {\n  color: red;\n}\n", encoding="utf-8")
    tool_config = {
        "id": "builtin_list_code_symbols",
        "name": "list_code_symbols",
        "source": "builtin",
        "schemaJson": json.dumps({"type": "object", "x-graphic": {"kind": "builtin_tool", "builtinId": "list_code_symbols"}}),
    }
    runtime = {
        "allowedRootsJson": json.dumps([str(root)]),
        "networkEnabled": True,
        "allowedHostsJson": "[]",
        "maxFileBytes": 4096,
        "maxHttpBytes": 1024,
    }

    py_symbols = tool_runtime_registry.invoke_registered_tool(tool_config, {"path": "module.py"}, runtime)
    html_symbols = tool_runtime_registry.invoke_registered_tool(tool_config, {"path": "index.html"}, runtime)
    js_symbols = tool_runtime_registry.invoke_registered_tool(tool_config, {"path": "app.tsx"}, runtime)
    css_symbols = tool_runtime_registry.invoke_registered_tool(tool_config, {"path": "style.css"}, runtime)

    assert py_symbols["ok"] is True
    assert {item["name"] for item in py_symbols["result"]["symbols"]} == {"Service", "Service.run", "helper"}
    assert html_symbols["ok"] is True
    assert html_symbols["result"]["symbols"][0]["name"] == "main#app"
    assert any(item["name"] == "Card" for item in js_symbols["result"]["symbols"])
    assert css_symbols["result"]["symbols"][0]["name"] == ".hero"


def test_tools_agent_can_search_then_read_file_chunk(monkeypatch, tmp_path: Path):
    docs = tmp_path / "repo"
    docs.mkdir()
    target = docs / "app.py"
    target.write_text("def target():\n    return 'ok'\n", encoding="utf-8")
    seen_messages = []

    def fake_call_chat_model(provider, model, messages, runtime_config=None):
        seen_messages.append(messages)
        if len(seen_messages) == 1:
            return FakeResponse(json.dumps({"tool_calls": [{"tool": "search_code", "args": {"root": ".", "query": "target", "file_glob": "*.py"}}], "final_answer": ""}))
        if len(seen_messages) == 2:
            return FakeResponse(json.dumps({"tool_calls": [{"tool": "read_file_chunk", "args": {"path": "app.py", "start_line": 1, "end_line": 2}}], "final_answer": ""}))
        return FakeResponse(json.dumps({"tool_calls": [], "final_answer": "target 返回 ok"}))

    monkeypatch.setattr(model_runtime, "call_chat_model", fake_call_chat_model)
    project = create_default_project("代码读取 Agent")
    project.state.fields.extend([StateField(name="tools_result", type="str"), StateField(name="tools_result_tool_calls", type="list")])
    for builtin_id, name in [("search_code", "search_code"), ("read_file_chunk", "read_file_chunk")]:
        schema = {"type": "object", "x-graphic": {"kind": "builtin_tool", "builtinId": builtin_id}}
        project.tools.append(ToolConfig(id=f"builtin_{builtin_id}", name=name, description=name, source="builtin", schemaJson=json.dumps(schema)))
    project.nodes.append(
        NodeIR(
            id="tools_agent",
            type=NodeType.TOOL,
            label="Tools",
            config={"toolIdsJson": json.dumps(["builtin_search_code", "builtin_read_file_chunk"]), "outputField": "tools_result", "maxIterations": 3},
        )
    )
    project.edges.append(EdgeIR(id="e1", source="start", target="tools_agent"))
    runtime = {
        "allowedRootsJson": json.dumps([str(docs)]),
        "networkEnabled": True,
        "allowedHostsJson": "[]",
        "maxFileBytes": 4096,
        "maxHttpBytes": 1024,
    }

    trace, state = preview.run_project_preview(project, {"messages": "查找 target"}, "live", None, runtime)

    assert trace[0]["status"] == "ok"
    assert state["tools_result"] == "target 返回 ok"
    assert [call["tool"] for call in state["tools_result_tool_calls"]] == ["search_code", "read_file_chunk"]
    assert "读取代码或大文件" in seen_messages[0][0][1]


def test_builtin_extract_html_supports_selectors_modes_and_errors(tmp_path: Path):
    root = tmp_path / "site"
    root.mkdir()
    html_file = root / "index.html"
    html_file.write_bytes(
        b"""<!doctype html>
<main id=\"app\">
  <section class=\"card hero\" data-kind=\"primary\">
    <h1>Hello</h1>
    <p>Welcome <strong>home</strong></p>
  </section>
  <section class=\"card secondary\">Other</section>
</main>
"""
    )
    outside = tmp_path / "outside.html"
    outside.write_text("<main></main>", encoding="utf-8")
    binary = root / "image.bin"
    binary.write_bytes(b"\x00<html>")
    tool_config = {
        "id": "builtin_extract_html",
        "name": "extract_html",
        "source": "builtin",
        "schemaJson": json.dumps({"type": "object", "x-graphic": {"kind": "builtin_tool", "builtinId": "extract_html"}}),
    }
    runtime = {
        "allowedRootsJson": json.dumps([str(root)]),
        "networkEnabled": True,
        "allowedHostsJson": "[]",
        "maxFileBytes": 4096,
        "maxHttpBytes": 1024,
    }

    html_result = tool_runtime_registry.invoke_registered_tool(tool_config, {"path": "index.html", "selector": "main .card", "mode": "html", "max_results": 1}, runtime)
    text_result = tool_runtime_registry.invoke_registered_tool(tool_config, {"path": "index.html", "selector": "#app .hero", "mode": "text"}, runtime)
    attrs_result = tool_runtime_registry.invoke_registered_tool(tool_config, {"path": "index.html", "selector": "section.secondary", "mode": "attributes"}, runtime)
    empty_result = tool_runtime_registry.invoke_registered_tool(tool_config, {"path": "index.html", "selector": ".missing"}, runtime)
    empty_selector = tool_runtime_registry.invoke_registered_tool(tool_config, {"path": "index.html", "selector": ""}, runtime)
    outside_result = tool_runtime_registry.invoke_registered_tool(tool_config, {"path": str(outside), "selector": "main"}, runtime)
    binary_result = tool_runtime_registry.invoke_registered_tool(tool_config, {"path": "image.bin", "selector": "html"}, runtime)
    truncated_result = tool_runtime_registry.invoke_registered_tool(tool_config, {"path": "index.html", "selector": "section", "max_results": 1, "max_chars": 10}, runtime)

    assert html_result["ok"] is True
    assert html_result["result"]["count"] == 1
    assert html_result["result"]["totalMatched"] == 2
    assert "data-kind" in html_result["result"]["matches"][0]["html"]
    assert html_result["result"]["matches"][0]["startLine"] == 3
    assert text_result["result"]["matches"][0]["text"] == "Hello Welcome home"
    assert attrs_result["result"]["matches"][0]["attributes"]["class"] == "card secondary"
    assert empty_result["ok"] is True
    assert empty_result["result"]["matches"] == []
    assert empty_selector["ok"] is False
    assert outside_result["ok"] is False
    assert "允许目录" in outside_result["error"]
    assert binary_result["ok"] is False
    assert truncated_result["result"]["truncated"] is True
    assert truncated_result["result"]["matches"][0]["truncated"] is True


def test_builtin_extract_css_rules_supports_selector_property_query_and_errors(tmp_path: Path):
    root = tmp_path / "site"
    root.mkdir()
    css_file = root / "style.css"
    css_file.write_bytes(
        b"""/* hidden { color: blue; } */
.card,
.panel {
  display: grid;
  color: red;
}

.button {
  color: white;
  margin: 0;
}
"""
    )
    outside = tmp_path / "outside.css"
    outside.write_text(".x { color: black; }", encoding="utf-8")
    binary = root / "style.bin"
    binary.write_bytes(b"\x00.card { color: red; }")
    tool_config = {
        "id": "builtin_extract_css_rules",
        "name": "extract_css_rules",
        "source": "builtin",
        "schemaJson": json.dumps({"type": "object", "x-graphic": {"kind": "builtin_tool", "builtinId": "extract_css_rules"}}),
    }
    runtime = {
        "allowedRootsJson": json.dumps([str(root)]),
        "networkEnabled": True,
        "allowedHostsJson": "[]",
        "maxFileBytes": 4096,
        "maxHttpBytes": 1024,
    }

    by_selector = tool_runtime_registry.invoke_registered_tool(tool_config, {"path": "style.css", "selector": ".panel"}, runtime)
    by_property = tool_runtime_registry.invoke_registered_tool(tool_config, {"path": "style.css", "property": "margin"}, runtime)
    by_query = tool_runtime_registry.invoke_registered_tool(tool_config, {"path": "style.css", "query": "display: grid"}, runtime)
    truncated = tool_runtime_registry.invoke_registered_tool(tool_config, {"path": "style.css", "property": "color", "max_results": 1}, runtime)
    missing_filter = tool_runtime_registry.invoke_registered_tool(tool_config, {"path": "style.css"}, runtime)
    outside_result = tool_runtime_registry.invoke_registered_tool(tool_config, {"path": str(outside), "selector": ".x"}, runtime)
    binary_result = tool_runtime_registry.invoke_registered_tool(tool_config, {"path": "style.bin", "selector": ".card"}, runtime)

    assert by_selector["ok"] is True
    rule = by_selector["result"]["rules"][0]
    assert rule["selectors"] == [".card", ".panel"]
    assert rule["declarations"]["display"] == "grid"
    assert rule["declarations"]["color"] == "red"
    assert rule["startLine"] == 2
    assert by_property["result"]["rules"][0]["selector"] == ".button"
    assert by_query["result"]["rules"][0]["selector"] == ".card,\n.panel"
    assert truncated["result"]["totalMatched"] == 2
    assert truncated["result"]["truncated"] is True
    assert "hidden" not in json.dumps(by_selector["result"], ensure_ascii=False)
    assert missing_filter["ok"] is False
    assert outside_result["ok"] is False
    assert "允许目录" in outside_result["error"]
    assert binary_result["ok"] is False


def test_tools_agent_can_extract_html_then_css_rules(monkeypatch, tmp_path: Path):
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text('<main><section class="hero">Hello</section></main>', encoding="utf-8")
    (site / "style.css").write_text(".hero {\n  display: grid;\n}\n", encoding="utf-8")
    seen_messages = []

    def fake_call_chat_model(provider, model, messages, runtime_config=None):
        seen_messages.append(messages)
        if len(seen_messages) == 1:
            return FakeResponse(json.dumps({"tool_calls": [{"tool": "extract_html", "args": {"path": "index.html", "selector": ".hero", "mode": "text"}}], "final_answer": ""}))
        if len(seen_messages) == 2:
            return FakeResponse(json.dumps({"tool_calls": [{"tool": "extract_css_rules", "args": {"path": "style.css", "selector": ".hero"}}], "final_answer": ""}))
        return FakeResponse(json.dumps({"tool_calls": [], "final_answer": "hero 使用 grid 布局"}))

    monkeypatch.setattr(model_runtime, "call_chat_model", fake_call_chat_model)
    project = create_default_project("HTML CSS Agent")
    project.state.fields.extend([StateField(name="tools_result", type="str"), StateField(name="tools_result_tool_calls", type="list")])
    for builtin_id, name in [("extract_html", "extract_html"), ("extract_css_rules", "extract_css_rules")]:
        schema = {"type": "object", "x-graphic": {"kind": "builtin_tool", "builtinId": builtin_id}}
        project.tools.append(ToolConfig(id=f"builtin_{builtin_id}", name=name, description=name, source="builtin", schemaJson=json.dumps(schema)))
    project.nodes.append(
        NodeIR(
            id="tools_agent",
            type=NodeType.TOOL,
            label="Tools",
            config={"toolIdsJson": json.dumps(["builtin_extract_html", "builtin_extract_css_rules"]), "outputField": "tools_result", "maxIterations": 3},
        )
    )
    project.edges.append(EdgeIR(id="e1", source="start", target="tools_agent"))
    runtime = {
        "allowedRootsJson": json.dumps([str(site)]),
        "networkEnabled": True,
        "allowedHostsJson": "[]",
        "maxFileBytes": 4096,
        "maxHttpBytes": 1024,
    }

    trace, state = preview.run_project_preview(project, {"messages": "分析 hero"}, "live", None, runtime)

    assert trace[0]["status"] == "ok"
    assert state["tools_result"] == "hero 使用 grid 布局"
    assert [call["tool"] for call in state["tools_result_tool_calls"]] == ["extract_html", "extract_css_rules"]
    assert "读取 HTML 时优先使用 extract_html" in seen_messages[0][0][1]
    assert "读取 CSS 时优先使用 extract_css_rules" in seen_messages[0][0][1]


def test_builtin_phase5_page_tools_support_text_css_structure_and_assets(tmp_path: Path):
    site = tmp_path / "site"
    site.mkdir()
    assets = site / "assets"
    assets.mkdir()
    (assets / "hero.png").write_bytes(b"png")
    (assets / "bg.png").write_bytes(b"png")
    html_file = site / "index.html"
    html_file.write_text(
        """<!doctype html>
<html>
<head>
  <title>Demo Page</title>
  <link rel="stylesheet" href="./style.css">
</head>
<body>
  <main id="app" class="page">
    <section id="hero" class="hero primary">
      <h1>Welcome Home</h1>
      <p>Find local assets and page styles.</p>
      <img src="assets/hero.png" alt="Hero">
      <a href="https://example.com">External</a>
      <form action="/search" method="get"><input name="q"><button type="submit">Search</button></form>
    </section>
  </main>
  <script src="./app.js"></script>
</body>
</html>
""",
        encoding="utf-8",
    )
    css_file = site / "style.css"
    css_file.write_text(
        """.hero, .card {
  color: red;
}
.page .hero {
  background-image: url("./assets/bg.png");
}
main > section.primary {
  display: grid;
}
""",
        encoding="utf-8",
    )
    (site / "app.js").write_text("console.log('ok')", encoding="utf-8")
    runtime = {
        "allowedRootsJson": json.dumps([str(site)]),
        "networkEnabled": True,
        "allowedHostsJson": "[]",
        "maxFileBytes": 8192,
        "maxHttpBytes": 1024,
    }

    html_by_text_tool = {
        "id": "builtin_extract_html_by_text",
        "name": "extract_html_by_text",
        "source": "builtin",
        "schemaJson": json.dumps({"type": "object", "x-graphic": {"kind": "builtin_tool", "builtinId": "extract_html_by_text"}}),
    }
    css_for_html_tool = {
        "id": "builtin_extract_css_for_html",
        "name": "extract_css_for_html",
        "source": "builtin",
        "schemaJson": json.dumps({"type": "object", "x-graphic": {"kind": "builtin_tool", "builtinId": "extract_css_for_html"}}),
    }
    structure_tool = {
        "id": "builtin_summarize_page_structure",
        "name": "summarize_page_structure",
        "source": "builtin",
        "schemaJson": json.dumps({"type": "object", "x-graphic": {"kind": "builtin_tool", "builtinId": "summarize_page_structure"}}),
    }
    assets_tool = {
        "id": "builtin_resolve_asset_references",
        "name": "resolve_asset_references",
        "source": "builtin",
        "schemaJson": json.dumps({"type": "object", "x-graphic": {"kind": "builtin_tool", "builtinId": "resolve_asset_references"}}),
    }

    text_result = tool_runtime_registry.invoke_registered_tool(html_by_text_tool, {"path": "index.html", "query": "Welcome Home", "mode": "text"}, runtime)
    regex_result = tool_runtime_registry.invoke_registered_tool(html_by_text_tool, {"path": "index.html", "query": "Welcome\\s+Home", "regex": True, "mode": "attributes"}, runtime)
    css_result = tool_runtime_registry.invoke_registered_tool(css_for_html_tool, {"path": "style.css", "html_path": "index.html", "selector": "#hero"}, runtime)
    structure_result = tool_runtime_registry.invoke_registered_tool(structure_tool, {"path": "index.html"}, runtime)
    html_assets = tool_runtime_registry.invoke_registered_tool(assets_tool, {"path": "index.html"}, runtime)
    css_assets = tool_runtime_registry.invoke_registered_tool(assets_tool, {"path": "style.css", "language": "css"}, runtime)

    assert text_result["ok"] is True
    assert text_result["result"]["matches"][0]["tag"] == "h1"
    assert text_result["result"]["matches"][0]["text"] == "Welcome Home"
    assert regex_result["ok"] is True
    assert regex_result["result"]["matches"][0]["selectorHint"] == "h1"
    assert css_result["ok"] is True
    selectors = {rule["selector"] for rule in css_result["result"]["rules"]}
    assert ".hero, .card" in selectors
    assert ".page .hero" in selectors
    assert "main > section.primary" in selectors
    assert "#hero" in css_result["result"]["queryTokens"]
    assert ".hero" in css_result["result"]["queryTokens"]
    assert structure_result["ok"] is True
    assert structure_result["result"]["title"] == "Demo Page"
    assert structure_result["result"]["headings"][0]["text"] == "Welcome Home"
    assert structure_result["result"]["forms"][0]["controls"][0]["name"] == "q"
    assert structure_result["result"]["stylesheets"][0]["href"] == "./style.css"
    assert html_assets["ok"] is True
    by_url = {item["url"]: item for item in html_assets["result"]["references"]}
    assert by_url["./style.css"]["exists"] is True
    assert by_url["assets/hero.png"]["exists"] is True
    assert by_url["https://example.com"]["external"] is True
    assert css_assets["ok"] is True
    assert css_assets["result"]["references"][0]["url"] == "./assets/bg.png"
    assert css_assets["result"]["references"][0]["exists"] is True


def test_tools_agent_prompt_mentions_phase5_page_tools(monkeypatch, tmp_path: Path):
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("<main><h1>Hello</h1></main>", encoding="utf-8")
    seen_messages = []

    def fake_call_chat_model(provider, model, messages, runtime_config=None):
        seen_messages.append(messages)
        return FakeResponse(json.dumps({"tool_calls": [], "final_answer": "ok"}))

    monkeypatch.setattr(model_runtime, "call_chat_model", fake_call_chat_model)
    project = create_default_project("页面分析 Agent")
    project.state.fields.append(StateField(name="tools_result", type="str"))
    for builtin_id, name in [
        ("summarize_page_structure", "summarize_page_structure"),
        ("extract_html_by_text", "extract_html_by_text"),
        ("extract_css_for_html", "extract_css_for_html"),
        ("resolve_asset_references", "resolve_asset_references"),
    ]:
        schema = {"type": "object", "x-graphic": {"kind": "builtin_tool", "builtinId": builtin_id}}
        project.tools.append(ToolConfig(id=f"builtin_{builtin_id}", name=name, description=name, source="builtin", schemaJson=json.dumps(schema)))
    project.nodes.append(
        NodeIR(
            id="tools_agent",
            type=NodeType.TOOL,
            label="Tools",
            config={
                "toolIdsJson": json.dumps(
                    [
                        "builtin_summarize_page_structure",
                        "builtin_extract_html_by_text",
                        "builtin_extract_css_for_html",
                        "builtin_resolve_asset_references",
                    ]
                ),
                "outputField": "tools_result",
                "maxIterations": 1,
            },
        )
    )
    project.edges.append(EdgeIR(id="e1", source="start", target="tools_agent"))
    runtime = {
        "allowedRootsJson": json.dumps([str(site)]),
        "networkEnabled": True,
        "allowedHostsJson": "[]",
        "maxFileBytes": 4096,
        "maxHttpBytes": 1024,
    }

    trace, state = preview.run_project_preview(project, {"messages": "分析页面"}, "live", None, runtime)

    assert trace[0]["status"] == "ok"
    assert state["tools_result"] == "ok"
    assert "summarize_page_structure" in seen_messages[0][0][1]
    assert "extract_html_by_text" in seen_messages[0][0][1]
    assert "resolve_asset_references" in seen_messages[0][0][1]


def test_phase6_tools_agent_records_recommended_next_tools_for_truncated_html(monkeypatch, tmp_path: Path):
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text(
        "<!doctype html><html><body><main id='app'><section id='hero'>"
        + ("large content " * 120)
        + "</section></main></body></html>",
        encoding="utf-8",
    )
    seen_messages = []

    def fake_call_chat_model(provider, model, messages, runtime_config=None):
        seen_messages.append(messages)
        if len(seen_messages) == 1:
            return FakeResponse(json.dumps({"tool_calls": [{"tool": "read_file", "args": {"path": "index.html"}}], "final_answer": ""}))
        return FakeResponse(json.dumps({"tool_calls": [], "final_answer": "已读取截断结果并给出下一步建议"}))

    monkeypatch.setattr(model_runtime, "call_chat_model", fake_call_chat_model)
    project = create_default_project("Phase6 Tools 策略")
    project.state.fields.extend([StateField(name="tools_result", type="str"), StateField(name="tools_result_tool_calls", type="list")])
    builtin_ids = [
        "read_file",
        "read_file_chunk",
        "search_code",
        "chunk_code_semantic",
        "extract_html",
        "summarize_page_structure",
        "web_search",
    ]
    for builtin_id in builtin_ids:
        schema = {"type": "object", "x-graphic": {"kind": "builtin_tool", "builtinId": builtin_id}}
        project.tools.append(ToolConfig(id=f"builtin_{builtin_id}", name=builtin_id, description=builtin_id, source="builtin", schemaJson=json.dumps(schema)))
    project.nodes.append(
        NodeIR(
            id="tools_agent",
            type=NodeType.TOOL,
            label="Tools",
            config={"toolIdsJson": json.dumps([f"builtin_{item}" for item in builtin_ids]), "outputField": "tools_result", "maxIterations": 2},
        )
    )
    project.edges.append(EdgeIR(id="e1", source="start", target="tools_agent"))
    runtime = {
        "allowedRootsJson": json.dumps([str(site)]),
        "networkEnabled": True,
        "allowedHostsJson": "[]",
        "maxFileBytes": 260,
        "maxHttpBytes": 1024,
    }

    trace, state = preview.run_project_preview(project, {"messages": "分析页面"}, "live", None, runtime)

    assert trace[0]["status"] == "ok"
    assert state["tools_result"] == "已读取截断结果并给出下一步建议"
    system_prompt = seen_messages[0][0][1]
    assert "read_file 截断处理" in system_prompt
    assert "代码阅读策略" in system_prompt
    assert "页面分析策略" in system_prompt
    assert "RAG/知识库文件读取策略" in system_prompt
    assert "网络搜索策略" in system_prompt
    first_call = state["tools_result_tool_calls"][0]
    assert first_call["observation"]["result"]["truncated"] is True
    recommended_tools = {item["tool"] for item in first_call["recommendedNextTools"]}
    assert "read_file_chunk" in recommended_tools
    assert "extract_html" in recommended_tools


def test_phase6_tool_error_classification(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    read_file_tool = {
        "id": "builtin_read_file",
        "name": "read_file",
        "source": "builtin",
        "schemaJson": json.dumps({"type": "object", "x-graphic": {"kind": "builtin_tool", "builtinId": "read_file"}}),
    }
    web_search_tool = {
        "id": "builtin_web_search",
        "name": "web_search",
        "source": "builtin",
        "schemaJson": json.dumps({"type": "object", "x-graphic": {"kind": "builtin_tool", "builtinId": "web_search"}}),
    }
    runtime = {
        "allowedRootsJson": json.dumps([str(root)]),
        "networkEnabled": False,
        "allowedHostsJson": "[]",
        "maxFileBytes": 1024,
        "maxHttpBytes": 1024,
    }

    missing_arg = tool_runtime_registry.invoke_registered_tool(read_file_tool, {}, runtime)
    outside_result = tool_runtime_registry.invoke_registered_tool(read_file_tool, {"path": str(outside)}, runtime)
    network_result = tool_runtime_registry.invoke_registered_tool(web_search_tool, {"query": "test"}, runtime)

    assert missing_arg["ok"] is False
    assert missing_arg["errorType"] == "tool_args"
    assert outside_result["ok"] is False
    assert outside_result["errorType"] == "path_permission"
    assert network_result["ok"] is False
    assert network_result["errorType"] == "network_permission"


def test_task_splitter_parses_markdown_json_and_fallback():
    splitter = NodeIR(
        id="splitter",
        type=NodeType.TASK_SPLITTER,
        label="拆分任务",
        config={"inputField": "task_plan", "outputField": "worker_tasks", "maxTasks": 2, "fallbackToSingleTask": True},
    )
    state = {
        "messages": "分析项目",
        "task_plan": '```json\n{"tasks":[{"title":"入口","goal":"分析入口","targetFiles":["frontend/src/App.tsx"]},{"goal":"分析后端"},{"goal":"超出限制"}]}\n```',
    }

    delta, detail = task_splitter_node.execute_live_task_splitter(splitter, state)
    fallback_delta, _detail = task_splitter_node.execute_live_task_splitter(splitter, {"messages": "兜底问题", "task_plan": "not json"})

    assert "2 个 Worker 任务" in detail
    assert [item["id"] for item in delta["worker_tasks"]] == ["task_1", "task_2"]
    assert delta["worker_tasks"][0]["targetFiles"] == ["frontend/src/App.tsx"]
    assert fallback_delta["worker_tasks"][0]["goal"] == "兜底问题"


def test_parallel_tools_stream_runs_explicit_worker_nodes(monkeypatch, tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "app.py").write_text("def app():\n    return 'ok'\n", encoding="utf-8")

    def fake_call_chat_model(provider, model, messages, runtime_config=None):
        user = messages[-1][1]
        payload = json.dumps(
            {
                "summary": "完成 " + ("入口" if "入口" in user else "后端"),
                "evidence": [{"path": "app.py", "symbol": "app", "startLine": 1, "endLine": 2, "note": "测试证据"}],
                "warnings": [],
            },
            ensure_ascii=False,
        )
        return FakeResponse(json.dumps({"tool_calls": [], "final_answer": payload}, ensure_ascii=False))

    monkeypatch.setattr(model_runtime, "call_chat_model", fake_call_chat_model)
    project = create_default_project("并行代码阅读")
    project.state.fields.extend([StateField(name="worker_tasks", type="list"), StateField(name="worker_results", type="list"), StateField(name="final_answer", type="str")])
    project.tools.append(
        ToolConfig(
            id="builtin_search_code",
            name="search_code",
            description="search_code",
            source="builtin",
            schemaJson=json.dumps({"type": "object", "x-graphic": {"kind": "builtin_tool", "builtinId": "search_code"}}),
        )
    )
    project.nodes.extend(
        [
            NodeIR(
                id="parallel",
                type=NodeType.PARALLEL_TOOLS,
                label="并行 Worker",
                config={
                    "tasksField": "worker_tasks",
                    "outputField": "worker_results",
                    "toolIdsJson": json.dumps(["builtin_search_code"]),
                    "toolRegistryJson": json.dumps([project.tools[0].model_dump(by_alias=True)]),
                    "maxConcurrentWorkers": 2,
                    "maxIterationsPerTask": 2,
                },
            ),
            NodeIR(id="parallel_worker_1", type=NodeType.PARALLEL_WORKER, label="Worker 1", config={"parentNodeId": "parallel", "workerIndex": 1}),
            NodeIR(id="parallel_worker_2", type=NodeType.PARALLEL_WORKER, label="Worker 2", config={"parentNodeId": "parallel", "workerIndex": 2}),
            NodeIR(id="reply", type=NodeType.DIRECT_REPLY, label="回复", config={"template": "{{ state.worker_results }}", "outputField": "final_answer"}),
        ]
    )
    project.edges.extend(
        [
            EdgeIR(id="e1", source="start", target="parallel"),
            EdgeIR(id="ew1", source="parallel", target="parallel_worker_1", kind=EdgeKind.WORKER),
            EdgeIR(id="ew2", source="parallel", target="parallel_worker_2", kind=EdgeKind.WORKER),
            EdgeIR(id="ewo1", source="parallel_worker_1", target="reply", kind=EdgeKind.WORKER),
            EdgeIR(id="ewo2", source="parallel_worker_2", target="reply", kind=EdgeKind.WORKER),
        ]
    )
    runtime = {"allowedRootsJson": json.dumps([str(root)]), "networkEnabled": False, "allowedHostsJson": "[]", "maxFileBytes": 4096, "maxHttpBytes": 1024}
    input_state = {
        "messages": "分析项目",
        "worker_tasks": [
            {"id": "task_1", "title": "入口", "goal": "分析入口"},
            {"id": "task_2", "title": "后端", "goal": "分析后端"},
        ],
    }

    events = list(preview.iter_project_preview_events(project, input_state, "live", None, runtime))

    starts = [event for event in events if event["event"] == "node_start" and event["type"] == "parallel_worker"]
    ends = [event for event in events if event["event"] == "node_end" and event["traceItem"]["type"] == "parallel_worker"]
    parent_end_index = next(index for index, event in enumerate(events) if event["event"] == "node_end" and event["traceItem"]["nodeId"] == "parallel")
    first_worker_start_index = next(index for index, event in enumerate(events) if event["event"] == "node_start" and event["type"] == "parallel_worker")
    run_end = events[-1]
    assert len(starts) == 2
    assert len(ends) == 2
    assert first_worker_start_index < parent_end_index
    assert {event["nodeId"] for event in starts} == {"parallel_worker_1", "parallel_worker_2"}
    assert all("workerResults" in event["traceItem"]["outputDelta"] for event in ends)
    run_end_worker_trace = [item for item in run_end["trace"] if item["type"] == "parallel_worker"]
    assert {item["nodeId"] for item in run_end_worker_trace} == {"parallel_worker_1", "parallel_worker_2"}
    assert all("workerResults" in item["outputDelta"] for item in run_end_worker_trace)
    assert len(run_end["outputState"]["worker_results"]) == 2
    assert all(item["status"] == "ok" for item in run_end["outputState"]["worker_results"])


def test_parallel_tools_stream_partial_worker_error_is_non_fatal(monkeypatch, tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "app.py").write_text("def app():\n    return 'ok'\n", encoding="utf-8")

    def fake_call_chat_model(provider, model, messages, runtime_config=None):
        user = messages[-1][1]
        if "后端" in user:
            raise RuntimeError("worker boom")
        payload = json.dumps(
            {
                "summary": "完成入口",
                "evidence": [{"path": "app.py", "symbol": "app", "startLine": 1, "endLine": 2, "note": "测试证据"}],
                "warnings": [],
            },
            ensure_ascii=False,
        )
        return FakeResponse(json.dumps({"tool_calls": [], "final_answer": payload}, ensure_ascii=False))

    monkeypatch.setattr(model_runtime, "call_chat_model", fake_call_chat_model)
    project = create_default_project("并行代码阅读")
    project.state.fields.extend([StateField(name="worker_tasks", type="list"), StateField(name="worker_results", type="list"), StateField(name="final_answer", type="str")])
    project.tools.append(
        ToolConfig(
            id="builtin_search_code",
            name="search_code",
            description="search_code",
            source="builtin",
            schemaJson=json.dumps({"type": "object", "x-graphic": {"kind": "builtin_tool", "builtinId": "search_code"}}),
        )
    )
    project.nodes.extend(
        [
            NodeIR(
                id="parallel",
                type=NodeType.PARALLEL_TOOLS,
                label="并行 Worker",
                config={
                    "tasksField": "worker_tasks",
                    "outputField": "worker_results",
                    "toolIdsJson": json.dumps(["builtin_search_code"]),
                    "toolRegistryJson": json.dumps([project.tools[0].model_dump(by_alias=True)]),
                    "maxConcurrentWorkers": 2,
                    "maxIterationsPerTask": 2,
                },
            ),
            NodeIR(id="parallel_worker_1", type=NodeType.PARALLEL_WORKER, label="Worker 1", config={"parentNodeId": "parallel", "workerIndex": 1}),
            NodeIR(id="parallel_worker_2", type=NodeType.PARALLEL_WORKER, label="Worker 2", config={"parentNodeId": "parallel", "workerIndex": 2}),
            NodeIR(id="reply", type=NodeType.DIRECT_REPLY, label="回复", config={"template": "{{ state.worker_results }}", "outputField": "final_answer"}),
        ]
    )
    project.edges.extend(
        [
            EdgeIR(id="e1", source="start", target="parallel"),
            EdgeIR(id="ew1", source="parallel", target="parallel_worker_1", kind=EdgeKind.WORKER),
            EdgeIR(id="ew2", source="parallel", target="parallel_worker_2", kind=EdgeKind.WORKER),
            EdgeIR(id="ewo1", source="parallel_worker_1", target="reply", kind=EdgeKind.WORKER),
            EdgeIR(id="ewo2", source="parallel_worker_2", target="reply", kind=EdgeKind.WORKER),
        ]
    )
    runtime = {"allowedRootsJson": json.dumps([str(root)]), "networkEnabled": False, "allowedHostsJson": "[]", "maxFileBytes": 4096, "maxHttpBytes": 1024}
    input_state = {
        "messages": "分析项目",
        "worker_tasks": [
            {"id": "task_1", "title": "入口", "goal": "分析入口"},
            {"id": "task_2", "title": "后端", "goal": "分析后端"},
        ],
    }

    events = list(preview.iter_project_preview_events(project, input_state, "live", None, runtime))
    run_end = events[-1]
    worker_trace = [item for item in run_end["trace"] if item["type"] == "parallel_worker"]
    error_worker = next(item for item in worker_trace if item["status"] == "error")
    status, pending = run_status_from_state(run_end["trace"], run_end["outputState"])

    assert status == "completed"
    assert pending is None
    assert error_worker["nonFatal"] is True
    assert error_worker["handledByParent"] == "parallel_tools"
    assert any(item["status"] == "ok" for item in run_end["outputState"]["worker_results"])
    assert any(item["status"] == "error" for item in run_end["outputState"]["worker_results"])


def test_builtin_extract_code_symbol_supports_structured_languages_and_errors(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    py_file = root / "module.py"
    py_file.write_text(
        "class Service:\n"
        "    def run(self):\n"
        "        return 'service'\n\n"
        "class Worker:\n"
        "    def run(self):\n"
        "        return 'worker'\n\n"
        "def helper():\n"
        "    return 1\n",
        encoding="utf-8",
    )
    tsx_file = root / "app.tsx"
    tsx_file.write_text(
        "export function View() {\n  return <main />\n}\n\n"
        "const Card = () => <section className=\"card\" />\n"
        "class Store { run() { return 1 } }\n",
        encoding="utf-8",
    )
    html_file = root / "index.html"
    html_file.write_text(
        "<main id=\"app\">\n  <section id=\"hero\" class=\"hero primary\">Hi</section>\n</main>",
        encoding="utf-8",
    )
    css_file = root / "style.css"
    css_file.write_text(".hero, .card {\n  color: red;\n}\n", encoding="utf-8")
    outside = tmp_path / "outside.py"
    outside.write_text("def secret():\n    pass\n", encoding="utf-8")
    tool_config = {
        "id": "builtin_extract_code_symbol",
        "name": "extract_code_symbol",
        "source": "builtin",
        "schemaJson": json.dumps({"type": "object", "x-graphic": {"kind": "builtin_tool", "builtinId": "extract_code_symbol"}}),
    }
    runtime = {
        "allowedRootsJson": json.dumps([str(root)]),
        "networkEnabled": True,
        "allowedHostsJson": "[]",
        "maxFileBytes": 4096,
        "maxHttpBytes": 1024,
    }

    method = tool_runtime_registry.invoke_registered_tool(tool_config, {"path": "module.py", "symbol": "Service.run", "kind": "method", "include_context": True}, runtime)
    ambiguous = tool_runtime_registry.invoke_registered_tool(tool_config, {"path": "module.py", "symbol": "run", "kind": "method"}, runtime)
    component = tool_runtime_registry.invoke_registered_tool(tool_config, {"path": "app.tsx", "symbol": "Card", "kind": "component"}, runtime)
    html = tool_runtime_registry.invoke_registered_tool(tool_config, {"path": "index.html", "symbol": "#hero", "kind": "html"}, runtime)
    css = tool_runtime_registry.invoke_registered_tool(tool_config, {"path": "style.css", "symbol": ".card", "kind": "css"}, runtime)
    missing = tool_runtime_registry.invoke_registered_tool(tool_config, {"path": "module.py", "symbol": "missing"}, runtime)
    outside_result = tool_runtime_registry.invoke_registered_tool(tool_config, {"path": str(outside), "symbol": "secret"}, runtime)

    assert method["ok"] is True
    assert method["result"]["symbol"] == "Service.run"
    assert "return 'service'" in method["result"]["content"]
    assert "context" in method["result"]
    assert ambiguous["ok"] is True
    assert ambiguous["result"]["ambiguous"] is True
    assert ambiguous["result"]["alternatives"][0]["name"] == "Worker.run"
    assert component["ok"] is True
    assert component["result"]["kind"] == "component"
    assert "const Card" in component["result"]["content"]
    assert html["ok"] is True
    assert '<section id="hero"' in html["result"]["content"]
    assert css["ok"] is True
    assert "color: red" in css["result"]["content"]
    assert missing["ok"] is False
    assert "未找到符号" in missing["error"]
    assert outside_result["ok"] is False
    assert "允许目录" in outside_result["error"]


def test_builtin_chunk_code_semantic_returns_symbol_chunks(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    tsx_file = root / "app.tsx"
    tsx_file.write_text(
        "export function View() {\n  return <main />\n}\n\n"
        "const Card = () => <section className=\"card\" />\n"
        "class Store { run() { return 1 } }\n",
        encoding="utf-8",
    )
    tool_config = {
        "id": "builtin_chunk_code_semantic",
        "name": "chunk_code_semantic",
        "source": "builtin",
        "schemaJson": json.dumps({"type": "object", "x-graphic": {"kind": "builtin_tool", "builtinId": "chunk_code_semantic"}}),
    }
    runtime = {
        "allowedRootsJson": json.dumps([str(root)]),
        "networkEnabled": True,
        "allowedHostsJson": "[]",
        "maxFileBytes": 4096,
        "maxHttpBytes": 1024,
    }

    result = tool_runtime_registry.invoke_registered_tool(tool_config, {"path": "app.tsx", "max_chars": 80}, runtime)
    with_content = tool_runtime_registry.invoke_registered_tool(tool_config, {"path": "app.tsx", "include_content": True, "max_chunks": 1}, runtime)

    assert result["ok"] is True
    names = {item["name"] for item in result["result"]["chunks"]}
    assert {"View", "Card", "Store"}.issubset(names)
    assert all("content" not in item for item in result["result"]["chunks"])
    assert with_content["ok"] is True
    assert "content" in with_content["result"]["chunks"][0]
    assert with_content["result"]["truncated"] is True


def test_phase4_language_supports_sfc_styles_markdown_and_data_files(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    vue_file = root / "Component.vue"
    vue_file.write_text(
        """<template>
  <main id="app"><section class="card"><h1>Hello</h1></section></main>
</template>
<script setup lang="ts">
const Card = () => null
function loadData() {
  return 1
}
</script>
<style scoped lang="scss">
$brand: red;
.card {
  &__title {
    color: $brand;
  }
}
</style>
""",
        encoding="utf-8",
    )
    svelte_file = root / "Widget.svelte"
    svelte_file.write_text(
        """<script>
  export let title = "Hi";
</script>
<section class="widget">{title}</section>
<style>
.widget {
  display: grid;
}
</style>
""",
        encoding="utf-8",
    )
    scss_file = root / "style.scss"
    scss_file.write_text(
        """$brand: red;
@mixin center {
  display: flex;
}
.card {
  &__title {
    color: $brand;
  }
}
""",
        encoding="utf-8",
    )
    less_file = root / "theme.less"
    less_file.write_text(
        """@gap: 8px;
.panel {
  .title {
    margin: @gap;
  }
}
""",
        encoding="utf-8",
    )
    md_file = root / "README.md"
    md_file.write_text("# Intro\nhello\n\n## Usage\nrun it\n\n## API\ncall it\n", encoding="utf-8")
    json_file = root / "package.json"
    json_file.write_text('{"scripts":{"dev":"vite"},"dependencies":{"vue":"latest"}}', encoding="utf-8")
    yaml_file = root / "config.yaml"
    yaml_file.write_text("server:\n  port: 8000\nmodels:\n  - qwen\n", encoding="utf-8")
    runtime = {
        "allowedRootsJson": json.dumps([str(root)]),
        "networkEnabled": True,
        "allowedHostsJson": "[]",
        "maxFileBytes": 8192,
        "maxHttpBytes": 1024,
    }
    list_tool = {
        "id": "builtin_list_code_symbols",
        "name": "list_code_symbols",
        "source": "builtin",
        "schemaJson": json.dumps({"type": "object", "x-graphic": {"kind": "builtin_tool", "builtinId": "list_code_symbols"}}),
    }
    extract_tool = {
        "id": "builtin_extract_code_symbol",
        "name": "extract_code_symbol",
        "source": "builtin",
        "schemaJson": json.dumps({"type": "object", "x-graphic": {"kind": "builtin_tool", "builtinId": "extract_code_symbol"}}),
    }
    chunk_tool = {
        "id": "builtin_chunk_code_semantic",
        "name": "chunk_code_semantic",
        "source": "builtin",
        "schemaJson": json.dumps({"type": "object", "x-graphic": {"kind": "builtin_tool", "builtinId": "chunk_code_semantic"}}),
    }

    vue_symbols = tool_runtime_registry.invoke_registered_tool(list_tool, {"path": "Component.vue"}, runtime)
    svelte_symbols = tool_runtime_registry.invoke_registered_tool(list_tool, {"path": "Widget.svelte"}, runtime)
    scss_symbols = tool_runtime_registry.invoke_registered_tool(list_tool, {"path": "style.scss"}, runtime)
    less_symbols = tool_runtime_registry.invoke_registered_tool(list_tool, {"path": "theme.less"}, runtime)
    markdown_symbols = tool_runtime_registry.invoke_registered_tool(list_tool, {"path": "README.md"}, runtime)
    json_symbols = tool_runtime_registry.invoke_registered_tool(list_tool, {"path": "package.json"}, runtime)
    yaml_symbols = tool_runtime_registry.invoke_registered_tool(list_tool, {"path": "config.yaml"}, runtime)
    vue_style = tool_runtime_registry.invoke_registered_tool(extract_tool, {"path": "Component.vue", "symbol": ".card__title", "kind": "style_rule"}, runtime)
    markdown_usage = tool_runtime_registry.invoke_registered_tool(extract_tool, {"path": "README.md", "symbol": "Usage", "kind": "heading"}, runtime)
    json_scripts = tool_runtime_registry.invoke_registered_tool(extract_tool, {"path": "package.json", "symbol": "scripts", "kind": "data_key"}, runtime)
    vue_chunks = tool_runtime_registry.invoke_registered_tool(chunk_tool, {"path": "Component.vue", "max_chunks": 10}, runtime)

    assert vue_symbols["ok"] is True
    vue_names = {item["name"] for item in vue_symbols["result"]["symbols"]}
    assert {"template", "script setup", "style:scss", ".card__title", "loadData"}.issubset(vue_names)
    assert svelte_symbols["ok"] is True
    assert {"script", "style", ".widget"}.issubset({item["name"] for item in svelte_symbols["result"]["symbols"]})
    assert scss_symbols["ok"] is True
    scss_names = {item["name"] for item in scss_symbols["result"]["symbols"]}
    assert "$brand" in scss_names
    assert "center" in scss_names
    assert ".card__title" in scss_names
    assert less_symbols["ok"] is True
    assert ".panel .title" in {item["name"] for item in less_symbols["result"]["symbols"]}
    assert markdown_symbols["result"]["language"] == "markdown"
    assert {"Intro", "Usage", "API"} == {item["name"] for item in markdown_symbols["result"]["symbols"]}
    assert json_symbols["result"]["language"] == "json"
    assert {"scripts", "dependencies"} == {item["name"] for item in json_symbols["result"]["symbols"]}
    assert yaml_symbols["result"]["language"] == "yaml"
    assert {"server", "models"} == {item["name"] for item in yaml_symbols["result"]["symbols"]}
    assert vue_style["ok"] is True
    assert "color: $brand" in vue_style["result"]["content"]
    assert markdown_usage["ok"] is True
    assert "run it" in markdown_usage["result"]["content"]
    assert json_scripts["ok"] is True
    assert "vite" in json_scripts["result"]["content"]
    assert vue_chunks["ok"] is True
    assert {"template", "script setup", "style:scss"}.issubset({item["name"] for item in vue_chunks["result"]["chunks"]})


def test_tools_agent_can_chunk_then_extract_code_symbol(monkeypatch, tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("def target():\n    return 'ok'\n", encoding="utf-8")
    seen_messages = []

    def fake_call_chat_model(provider, model, messages, runtime_config=None):
        seen_messages.append(messages)
        if len(seen_messages) == 1:
            return FakeResponse(json.dumps({"tool_calls": [{"tool": "chunk_code_semantic", "args": {"path": "app.py"}}], "final_answer": ""}))
        if len(seen_messages) == 2:
            return FakeResponse(json.dumps({"tool_calls": [{"tool": "extract_code_symbol", "args": {"path": "app.py", "symbol": "target", "kind": "function"}}], "final_answer": ""}))
        return FakeResponse(json.dumps({"tool_calls": [], "final_answer": "target 返回 ok"}))

    monkeypatch.setattr(model_runtime, "call_chat_model", fake_call_chat_model)
    project = create_default_project("结构化代码 Agent")
    project.state.fields.extend([StateField(name="tools_result", type="str"), StateField(name="tools_result_tool_calls", type="list")])
    for builtin_id, name in [("chunk_code_semantic", "chunk_code_semantic"), ("extract_code_symbol", "extract_code_symbol")]:
        schema = {"type": "object", "x-graphic": {"kind": "builtin_tool", "builtinId": builtin_id}}
        project.tools.append(ToolConfig(id=f"builtin_{builtin_id}", name=name, description=name, source="builtin", schemaJson=json.dumps(schema)))
    project.nodes.append(
        NodeIR(
            id="tools_agent",
            type=NodeType.TOOL,
            label="Tools",
            config={"toolIdsJson": json.dumps(["builtin_chunk_code_semantic", "builtin_extract_code_symbol"]), "outputField": "tools_result", "maxIterations": 3},
        )
    )
    project.edges.append(EdgeIR(id="e1", source="start", target="tools_agent"))
    runtime = {
        "allowedRootsJson": json.dumps([str(repo)]),
        "networkEnabled": True,
        "allowedHostsJson": "[]",
        "maxFileBytes": 4096,
        "maxHttpBytes": 1024,
    }

    trace, state = preview.run_project_preview(project, {"messages": "读取 target"}, "live", None, runtime)

    assert trace[0]["status"] == "ok"
    assert state["tools_result"] == "target 返回 ok"
    assert [call["tool"] for call in state["tools_result_tool_calls"]] == ["chunk_code_semantic", "extract_code_symbol"]
    assert "优先使用 extract_code_symbol" in seen_messages[0][0][1]


def test_builtin_web_search_normalizes_duckduckgo_response(monkeypatch):
    class FakeHttpResponse:
        status_code = 200
        headers = {"content-type": "application/json"}
        content = b"{}"
        encoding = "utf-8"
        url = "https://api.duckduckgo.com/"

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "Answer": "42",
                "AbstractText": "摘要",
                "AbstractURL": "https://example.com",
                "Definition": "",
                "RelatedTopics": [{"Text": "主题 A", "FirstURL": "https://example.com/a"}],
            }

    seen = {}

    def fake_get(url, **kwargs):
        seen["url"] = url
        seen["kwargs"] = kwargs
        return FakeHttpResponse()

    monkeypatch.setattr(tool_runtime_web.httpx, "get", fake_get)
    tool_config = {
        "id": "builtin_web_search",
        "name": "web_search",
        "source": "builtin",
        "schemaJson": "{}",
    }
    runtime = {
        "allowedRootsJson": "[]",
        "networkEnabled": True,
        "allowedHostsJson": json.dumps(["api.duckduckgo.com"]),
        "maxFileBytes": 1024,
        "maxHttpBytes": 1024,
    }

    result = tool_runtime_registry.invoke_registered_tool(tool_config, {"query": "life", "max_results": 1, "mode": "auto"}, runtime)

    assert result["ok"] is True
    assert "format=json" in seen["url"]
    assert result["result"]["source"] == "duckduckgo_instant_answer"
    assert result["result"]["answer"] == "42"
    assert result["result"]["relatedTopics"][0]["title"] == "主题 A"


def test_builtin_web_search_falls_back_to_duckduckgo_html_serp(monkeypatch):
    class FakeInstantAnswerResponse:
        status_code = 200
        headers = {"content-type": "application/json"}
        content = b"{}"
        encoding = "utf-8"
        url = "https://api.duckduckgo.com/"
        text = ""

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "Answer": "",
                "AbstractText": "",
                "AbstractURL": "",
                "Definition": "",
                "RelatedTopics": [],
                "Results": [],
            }

    class FakeSerpResponse:
        status_code = 200
        headers = {"content-type": "text/html"}
        content = b""
        encoding = "utf-8"
        url = "https://html.duckduckgo.com/html/"
        text = """
        <html>
          <body>
            <a class="result__a" href="/l/?uddg=https%3A%2F%2Fwww.anthropic.com%2Fclaude%2Ffable">Claude Fable 5 - Anthropic</a>
            <a class="result__snippet">Claude Fable 5 introduces our 5th model generation.</a>
            <a class="result__a" href="https://www.anthropic.com/news/claude-fable-5-mythos-5">Claude Fable 5 and Mythos 5</a>
            <div class="result__snippet">Announcement page.</div>
          </body>
        </html>
        """

        def raise_for_status(self):
            return None

    seen_urls = []

    def fake_get(url, **kwargs):
        seen_urls.append(url)
        if "api.duckduckgo.com" in url:
            return FakeInstantAnswerResponse()
        return FakeSerpResponse()

    monkeypatch.setattr(tool_runtime_web.httpx, "get", fake_get)
    tool_config = {
        "id": "builtin_web_search",
        "name": "web_search",
        "source": "builtin",
        "schemaJson": json.dumps({"type": "object", "x-graphic": {"kind": "builtin_tool", "builtinId": "web_search"}}),
    }
    runtime = {
        "allowedRootsJson": "[]",
        "networkEnabled": True,
        "allowedHostsJson": json.dumps(["api.duckduckgo.com"]),
        "maxFileBytes": 1024,
        "maxHttpBytes": 1024,
    }

    result = tool_runtime_registry.invoke_registered_tool(tool_config, {"query": "claude 5 fable", "max_results": 2, "mode": "auto"}, runtime)

    assert result["ok"] is True
    assert any("api.duckduckgo.com" in url for url in seen_urls)
    assert any("html.duckduckgo.com" in url for url in seen_urls)
    assert result["result"]["source"] == "duckduckgo_serp_fallback"
    assert result["result"]["serpFallbackUsed"] is True
    assert result["result"]["serpResults"][0]["title"] == "Claude Fable 5 - Anthropic"
    assert result["result"]["serpResults"][0]["url"] == "https://www.anthropic.com/claude/fable"
    assert "5th model generation" in result["result"]["serpResults"][0]["snippet"]


def test_builtin_web_search_defaults_to_duckduckgo_html_serp(monkeypatch):
    class FakeSerpResponse:
        status_code = 200
        headers = {"content-type": "text/html"}
        content = b""
        encoding = "utf-8"
        url = "https://html.duckduckgo.com/html/"
        text = """
        <html>
          <body>
            <a class="result__a" href="https://www.anthropic.com/news/claude-fable-5-mythos-5">Claude Fable 5 and Mythos 5</a>
            <div class="result__snippet">Anthropic announcement page.</div>
          </body>
        </html>
        """

        def raise_for_status(self):
            return None

    seen_urls = []

    def fake_get(url, **kwargs):
        seen_urls.append(url)
        if "api.duckduckgo.com" in url:
            raise AssertionError("default web_search should not call Instant Answer")
        return FakeSerpResponse()

    monkeypatch.setattr(tool_runtime_web.httpx, "get", fake_get)
    tool_config = {
        "id": "builtin_web_search",
        "name": "web_search",
        "source": "builtin",
        "schemaJson": "{}",
    }
    runtime = {
        "allowedRootsJson": "[]",
        "networkEnabled": True,
        "allowedHostsJson": json.dumps(["api.duckduckgo.com"]),
        "maxFileBytes": 1024,
        "maxHttpBytes": 1024,
    }

    result = tool_runtime_registry.invoke_registered_tool(tool_config, {"query": "claude 5 fable", "max_results": 2}, runtime)

    assert result["ok"] is True
    assert seen_urls and all("html.duckduckgo.com" in url for url in seen_urls)
    assert result["result"]["searchMode"] == "serp"
    assert result["result"]["source"] == "duckduckgo_serp"
    assert result["result"]["serpFallbackUsed"] is False
    assert result["result"]["serpResults"][0]["title"] == "Claude Fable 5 and Mythos 5"


def test_tools_agent_uses_node_openai_compatible_config_and_nested_registry(monkeypatch):
    seen_calls = []

    class FakeHttpResponse:
        status_code = 200
        headers = {"content-type": "application/json"}
        content = b"{}"
        encoding = "utf-8"
        url = "https://api.duckduckgo.com/"

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "Answer": "search answer",
                "AbstractText": "search abstract",
                "AbstractURL": "https://example.com",
                "RelatedTopics": [{"Text": "related topic", "FirstURL": "https://example.com/topic"}],
            }

    def fake_get(url, **kwargs):
        return FakeHttpResponse()

    def fake_call_openai_compatible(provider, model, messages, base_url, api_key, api_key_env, organization):
        seen_calls.append(
            {
                "provider": provider,
                "model": model,
                "base_url": base_url,
                "api_key_env": api_key_env,
                "messages": messages,
            }
        )
        if len(seen_calls) == 1:
            return FakeResponse(json.dumps({"tool_calls": [{"tool": "web_search", "args": {"query": "claude 5 fable", "mode": "auto"}}], "final_answer": ""}))
        return FakeResponse(json.dumps({"tool_calls": [], "final_answer": "搜索完成"}))

    monkeypatch.setattr(tool_runtime_web.httpx, "get", fake_get)
    monkeypatch.setattr(model_runtime, "call_openai_compatible", fake_call_openai_compatible)

    project = create_default_project("嵌套工具注册表")
    project.state.fields.extend([StateField(name="tools_result", type="str"), StateField(name="tools_result_tool_calls", type="list")])
    tool_config = {
        "id": "builtin_web_search",
        "name": "web_search",
        "description": "DuckDuckGo",
        "source": "builtin",
        "schemaJson": json.dumps({"type": "object", "x-graphic": {"kind": "builtin_tool", "builtinId": "web_search"}}),
    }
    project.nodes.append(
        NodeIR(
            id="tools_agent",
            type=NodeType.TOOL,
            label="Tools",
            config={
                "provider": "mimo",
                "model": "mimo-v2.5-pro",
                "baseUrl": "https://token-plan-cn.xiaomimimo.com/v1",
                "apiKeyEnv": "MIMO_API_KEY",
                "apiFormat": "openai_compatible",
                "toolIdsJson": json.dumps(["builtin_web_search"]),
                "toolRegistryJson": json.dumps([[tool_config]]),
                "outputField": "tools_result",
            },
        )
    )
    project.edges.append(EdgeIR(id="e1", source="start", target="tools_agent"))

    trace, state = preview.run_project_preview(
        project,
        {"messages": "查询 claude 5 fable"},
        "live",
        {"provider": "openai", "model": "fallback"},
        {"networkEnabled": True, "allowedHostsJson": json.dumps(["api.duckduckgo.com"])},
    )

    assert trace[0]["status"] == "ok"
    assert state["tools_result"] == "搜索完成"
    assert state["tools_result_tool_calls"][0]["observation"]["result"]["answer"] == "search answer"
    assert seen_calls[0]["provider"] == "mimo"
    assert seen_calls[0]["model"] == "mimo-v2.5-pro"
    assert seen_calls[0]["base_url"] == "https://token-plan-cn.xiaomimimo.com/v1"
    assert seen_calls[0]["api_key_env"] == "MIMO_API_KEY"


def test_model_config_normalization_ignores_invalid_list_value():
    assert model_runtime.normalize_model_config([]) is None


def test_openai_compatible_base_url_can_run_without_configured_key(monkeypatch):
    seen = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            seen["kwargs"] = kwargs

        def invoke(self, messages):
            seen["messages"] = messages
            return FakeResponse("无密钥代理响应")

    monkeypatch.setitem(sys.modules, "langchain_openai", SimpleNamespace(ChatOpenAI=FakeChatOpenAI))

    response = model_runtime.call_chat_model(
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

    response = model_runtime.call_chat_model(
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
    monkeypatch.setattr(model_runtime, "call_openai_compatible_embedding", fake_embedding)

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

    monkeypatch.setattr(model_runtime, "call_chat_model", fake_call_chat_model)
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
        {"messages": "我要申请退款"},
        "live",
        {"provider": "openai", "model": "gpt-4.1-mini", "enabled": True},
    )

    assert [item["nodeId"] for item in refund_trace] == ["route_intent", "refund_approval"]
    assert {item["status"] for item in refund_trace} == {"ok"}
    assert refund_state["route_key"] == "refund"
    assert refund_state["_glg_run_status"] == "paused"
    assert refund_trace[-1]["pause"] is True
    assert refund_trace[-1]["approval"]["nodeId"] == "refund_approval"

    resumed_trace, resumed_state = preview.resume_project_preview(
        project,
        refund_state,
        "refund_approval",
        "approved",
        "同意退款",
        "live",
        {"provider": "openai", "model": "gpt-4.1-mini", "enabled": True},
    )

    assert [item["nodeId"] for item in resumed_trace] == ["refund_approval", "support_agent", "reply_support"]
    assert resumed_state["approval_action"] == "approved"
    assert resumed_state["approval_result"]["comment"] == "同意退款"
    assert "退款申请" in resumed_state["final_answer"]
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
