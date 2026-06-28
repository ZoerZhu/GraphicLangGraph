from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.config import ROOT_DIR
from app.ir.schemas import NodeIR

from .. import model_runtime
from ..common import first_config_value, parse_json_object, positive_int, render_template
from ..context import ExecutionContext


TEXT_SUFFIXES = {".md", ".markdown", ".txt"}


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
    root = resolve_path(str(config.get("path", "./knowledge")))
    top_k = positive_int(config.get("topK", 4), 4)
    query = render_template(str(config.get("query", "{{ state.messages }}")), state)
    if not root.exists():
        return {output_field: ""}, f"知识库目录不存在：{root}"

    if is_chroma_retriever(config, root):
        return execute_chroma_retriever(config, root, output_field, query, top_k)

    files = sorted(path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES)
    ranked = rank_documents(files, query)
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


def execute_chroma_retriever(config: dict[str, Any], root: Path, output_field: str, query: str, top_k: int):
    try:
        import chromadb
    except ImportError as exc:
        raise RuntimeError("后端缺少 chromadb，请安装 requirements-dev.txt 后重试。") from exc

    hints = chroma_runtime_hints(config, root)
    try:
        client = chromadb.PersistentClient(path=str(root))
        collection_name = first_config_value(
            config.get("collection"),
            hints.get("collection"),
            hints.get("collectionName"),
            hints.get("COLLECTION_NAME"),
        )
        collection = get_chroma_collection(client, collection_name)
        collection_name = getattr(collection, "name", collection_name or "default")
        count = int(collection.count())
        if count <= 0:
            return {output_field: ""}, f"Chroma collection {collection_name} 为空。"

        include = ["documents", "metadatas", "distances"]
        n_results = min(top_k, count)
        query_embedding = build_chroma_query_embedding(config, hints, query)
        if query_embedding:
            result = collection.query(query_embeddings=[query_embedding], n_results=n_results, include=include)
            detail_mode = "query_embeddings"
        else:
            result = collection.query(query_texts=[query], n_results=n_results, include=include)
            detail_mode = "query_texts"
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(format_chroma_error(exc, bool(chroma_embedding_model(config, hints)))) from exc

    context_parts = format_chroma_results(result)
    return {
        output_field: "\n\n---\n\n".join(context_parts),
    }, f"查询 Chroma collection {collection_name}（{count} 条，{detail_mode}），返回 {len(context_parts)} 段到 state.{output_field}"


def resolve_path(value: str) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return ROOT_DIR / path


def is_chroma_retriever(config: dict[str, Any], root: Path) -> bool:
    source = str(config.get("source", "")).strip().lower()
    source_type = str(config.get("sourceType", "")).strip().lower()
    return source == "vectorstore" or source_type == "vectorstore" or (root / "chroma.sqlite3").exists()


def get_chroma_collection(client: Any, collection_name: str) -> Any:
    if collection_name:
        return client.get_collection(name=collection_name)
    collections = client.list_collections()
    if not collections:
        raise RuntimeError("Chroma 目录中没有可用 collection。")
    first = collections[0]
    first_name = getattr(first, "name", str(first))
    return client.get_collection(name=first_name)


def chroma_runtime_hints(config: dict[str, Any], root: Path) -> dict[str, Any]:
    hints = parse_json_object(str(config.get("metadataJson", "") or "{}"))
    sidecar = read_chroma_sidecar_config(root)
    for key, value in sidecar.items():
        hints.setdefault(key, value)
    return hints


def read_chroma_sidecar_config(root: Path) -> dict[str, Any]:
    candidates = [root / "runtime_config.json", root.parent / "runtime_config.json"]
    for path in candidates:
        if not path.exists() or not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            return data
    return {}


def build_chroma_query_embedding(config: dict[str, Any], hints: dict[str, Any], query: str) -> list[float] | None:
    model = chroma_embedding_model(config, hints)
    base_url = first_config_value(
        hints.get("embeddingBaseUrl"),
        hints.get("embeddingApiBase"),
        hints.get("baseUrl"),
        hints.get("apiBase"),
        hints.get("EMBEDDING_API_BASE"),
    )
    api_key_env = first_config_value(hints.get("embeddingApiKeyEnv"), hints.get("apiKeyEnv"), hints.get("EMBEDDING_API_KEY_ENV"))
    api_key = first_config_value(hints.get("embeddingApiKey"), hints.get("apiKey"), hints.get("EMBEDDING_API_KEY"), model_runtime.read_api_key(api_key_env))
    if not model or not base_url:
        return None
    if not api_key:
        raise RuntimeError("Chroma 查询需要生成 query embedding，但没有可用的 embedding API Key。请在 RAG 元数据 JSON 配置 embeddingApiKeyEnv，或设置 EMBEDDING_API_KEY。")
    return model_runtime.call_openai_compatible_embedding(model, base_url, api_key, query)


def chroma_embedding_model(config: dict[str, Any], hints: dict[str, Any]) -> str:
    metadata_model = first_config_value(hints.get("embeddingModel"))
    if metadata_model:
        return metadata_model
    config_model = first_config_value(config.get("embeddingModel"))
    sidecar_model = first_config_value(hints.get("EMBEDDING_MODEL"))
    if config_model and config_model != "bge-m3":
        return config_model
    return sidecar_model or config_model


def format_chroma_results(result: dict[str, Any]) -> list[str]:
    ids = first_result_list(result.get("ids"))
    documents = first_result_list(result.get("documents"))
    metadatas = first_result_list(result.get("metadatas"))
    distances = first_result_list(result.get("distances"))
    context_parts: list[str] = []
    for index, document in enumerate(documents):
        text = "" if document is None else str(document)
        metadata = metadatas[index] if index < len(metadatas) and isinstance(metadatas[index], dict) else {}
        source = metadata_source(metadata) or (str(ids[index]) if index < len(ids) else f"document_{index + 1}")
        distance = distances[index] if index < len(distances) else None
        lines = [f"来源: {source}"]
        if distance is not None:
            lines.append(f"距离: {distance}")
        if metadata:
            lines.append(f"元数据: {json.dumps(metadata, ensure_ascii=False)}")
        lines.append(text[:2400])
        context_parts.append("\n".join(lines))
    return context_parts


def metadata_source(metadata: dict[str, Any]) -> str:
    for key in ("source", "file", "filename", "path", "url", "title"):
        value = metadata.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def first_result_list(value: Any) -> list[Any]:
    if not isinstance(value, list) or not value:
        return []
    first = value[0]
    return first if isinstance(first, list) else value


def format_chroma_error(exc: Exception, has_embedding_model: bool) -> str:
    message = str(exc)
    if "dimension" in message.lower() or "embedding" in message.lower():
        if has_embedding_model:
            return f"Chroma 查询失败：{message}"
        return (
            "Chroma 查询失败：该 collection 可能使用了非默认 embedding 维度。"
            "请在 RAG 配置中填写 Embedding 模型，并在元数据 JSON 配置 embeddingBaseUrl 与 embeddingApiKeyEnv。"
            f"原始错误：{message}"
        )
    return f"Chroma 查询失败：{message}"


def rank_documents(files: list[Path], query: str) -> list[tuple[int, Path, str]]:
    terms = query_terms(query)
    ranked: list[tuple[int, Path, str]] = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        lowered = text.lower()
        if not terms:
            score = 1
        else:
            score = sum(lowered.count(term) for term in terms)
        if score > 0:
            ranked.append((score, path, text))
    ranked.sort(key=lambda item: (-item[0], item[1].as_posix()))
    if ranked:
        return ranked

    fallback: list[tuple[int, Path, str]] = []
    for path in files:
        try:
            fallback.append((0, path, path.read_text(encoding="utf-8")))
        except UnicodeDecodeError:
            continue
    return fallback


def query_terms(query: str) -> list[str]:
    normalized = query.lower()
    terms = [term for term in re.split(r"[\s,，。！？；;:：、/\\]+", normalized) if len(term) >= 2]
    cjk_pairs = re.findall(r"[\u4e00-\u9fff]{2,}", normalized)
    for phrase in cjk_pairs:
        terms.extend(phrase[index : index + 2] for index in range(max(0, len(phrase) - 1)))
    return sorted(set(terms), key=lambda item: (-len(item), item))
