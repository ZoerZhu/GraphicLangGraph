import json
import sys
from types import SimpleNamespace
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
