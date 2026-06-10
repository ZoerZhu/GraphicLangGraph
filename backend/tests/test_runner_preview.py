from pathlib import Path

from app.ir.schemas import EdgeIR, NodeIR, NodeType, StateField, create_default_project
from app.runner import preview


class FakeResponse:
    def __init__(self, content: str) -> None:
        self.content = content


def test_live_preview_runs_knowledge_qa_chain(monkeypatch, tmp_path: Path):
    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()
    (knowledge_dir / "refund.md").write_text("退款政策：订单签收后 7 天内可以申请退款。", encoding="utf-8")

    def fake_call_chat_model(provider, model, messages):
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
