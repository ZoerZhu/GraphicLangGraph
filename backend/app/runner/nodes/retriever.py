from __future__ import annotations

from typing import Any

from app.ir.schemas import NodeIR

from .. import engine
from ..common import positive_int, render_template
from ..context import ExecutionContext


def execute_live(node: NodeIR, state: dict[str, Any], ctx: ExecutionContext):
    return execute_retriever(node, state)


def execute_dry(node: NodeIR, state: dict[str, Any], ctx: ExecutionContext):
    config = node.config
    field = str(config.get("outputField", "retrieved_context"))
    return {
        field: f"[dry-run] 从 {config.get('path', './knowledge')} 检索 top_k={config.get('topK', 4)}",
    }, f"模拟 Retriever 输出到 state.{field}"


def execute_retriever(node: NodeIR, state: dict[str, Any]):
    config = node.config
    output_field = str(config.get("outputField", f"{node.id}_context"))
    root = engine._resolve_path(str(config.get("path", "./knowledge")))
    top_k = positive_int(config.get("topK", 4), 4)
    query = render_template(str(config.get("query", "{{ state.messages }}")), state)
    if not root.exists():
        return {output_field: ""}, f"知识库目录不存在：{root}"

    if engine._is_chroma_retriever(config, root):
        return execute_chroma_retriever(config, root, output_field, query, top_k)

    files = sorted(path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in engine.TEXT_SUFFIXES)
    ranked = engine._rank_documents(files, query)
    selected = ranked[:top_k] if ranked else []
    context_parts = []
    for score, path, text in selected:
        try:
            source = path.relative_to(root).as_posix()
        except ValueError:
            source = path.as_posix()
        context_parts.append(f"来源: {source}\n相关度: {score}\n{text[:2400]}")
    return {
        output_field: "\n\n---\n\n".join(context_parts),
    }, f"检索 {len(files)} 个文档，返回 {len(context_parts)} 段到 state.{output_field}"


def execute_chroma_retriever(config: dict[str, Any], root: Any, output_field: str, query: str, top_k: int):
    try:
        import chromadb
    except ImportError as exc:
        raise RuntimeError("后端缺少 chromadb，请安装 requirements-dev.txt 后重试。") from exc

    hints = engine._chroma_runtime_hints(config, root)
    try:
        client = chromadb.PersistentClient(path=str(root))
        collection_name = engine._first_config_value(
            config.get("collection"),
            hints.get("collection"),
            hints.get("collectionName"),
            hints.get("COLLECTION_NAME"),
        )
        collection = engine._get_chroma_collection(client, collection_name)
        collection_name = getattr(collection, "name", collection_name or "default")
        count = int(collection.count())
        if count <= 0:
            return {output_field: ""}, f"Chroma collection {collection_name} 为空。"

        include = ["documents", "metadatas", "distances"]
        n_results = min(top_k, count)
        query_embedding = engine._build_chroma_query_embedding(config, hints, query)
        if query_embedding:
            result = collection.query(query_embeddings=[query_embedding], n_results=n_results, include=include)
            detail_mode = "query_embeddings"
        else:
            result = collection.query(query_texts=[query], n_results=n_results, include=include)
            detail_mode = "query_texts"
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(engine._format_chroma_error(exc, bool(engine._chroma_embedding_model(config, hints)))) from exc

    context_parts = engine._format_chroma_results(result)
    return {
        output_field: "\n\n---\n\n".join(context_parts),
    }, f"查询 Chroma collection {collection_name}（{count} 条，{detail_mode}），返回 {len(context_parts)} 段到 state.{output_field}"
