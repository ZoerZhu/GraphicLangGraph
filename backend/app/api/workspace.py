from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.config import WORKSPACE_MCP_FILE, WORKSPACE_MODELS_FILE, WORKSPACE_RAG_FILE, WORKSPACE_TOOLS_FILE, ensure_runtime_dirs


router = APIRouter(prefix="/api/workspace", tags=["workspace"])


class WorkspaceToolConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    id: str = Field(default_factory=lambda: f"tool_{uuid4().hex[:8]}")
    name: str = "未命名工具"
    description: str = ""
    source: str = "python"
    tool_schema: str = Field("{}", alias="schemaJson")


class WorkspaceMcpServerConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    id: str = Field(default_factory=lambda: f"mcp_{uuid4().hex[:8]}")
    name: str = "未命名 MCP"
    transport: str = "stdio"
    command: str = ""
    url: str = ""
    description: str = ""


class WorkspaceModelConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    id: str = Field(default_factory=lambda: f"model_{uuid4().hex[:8]}")
    name: str = "未命名模型配置"
    provider: str = "openai"
    model: str = "gpt-4.1-mini"
    base_url: str = Field("", alias="baseUrl")
    api_key: str = Field("", alias="apiKey")
    api_key_env: str = Field("", alias="apiKeyEnv")
    api_version: str = Field("", alias="apiVersion")
    organization: str = ""
    homepage: str = ""
    api_format: str = Field("openai_compatible", alias="apiFormat")
    extra_options_json: str = Field("{}", alias="extraOptionsJson")
    model_rows_json: str = Field("[]", alias="modelRowsJson")
    models_json: str = Field("{}", alias="modelsJson")
    enabled: bool = True
    is_default: bool = Field(False, alias="isDefault")
    notes: str = ""


class WorkspaceRagKnowledgeBase(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    id: str = Field(default_factory=lambda: f"rag_{uuid4().hex[:8]}")
    name: str = "未命名知识库"
    source_type: str = Field("local_directory", alias="sourceType")
    path: str = ""
    url: str = ""
    collection: str = ""
    description: str = ""
    embedding_model: str = Field("", alias="embeddingModel")
    top_k: int = Field(4, alias="topK")
    metadata_json: str = Field("{}", alias="metadataJson")
    enabled: bool = True


class RagPathInspectRequest(BaseModel):
    path: str


class RagPathInspectResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    exists: bool
    source_type: str = Field("local_directory", alias="sourceType")
    path: str = ""
    url: str = ""
    collection: str = ""
    description: str = ""
    embedding_model: str = Field("", alias="embeddingModel")
    top_k: int = Field(4, alias="topK")
    metadata_json: str = Field("{}", alias="metadataJson")
    detected_files: list[str] = Field(default_factory=list, alias="detectedFiles")
    warnings: list[str] = Field(default_factory=list)


@router.get("/tools", response_model=list[WorkspaceToolConfig])
def list_tool_configs() -> list[WorkspaceToolConfig]:
    return _read_tool_configs()


@router.put("/tools", response_model=list[WorkspaceToolConfig])
def save_tool_configs(configs: list[WorkspaceToolConfig]) -> list[WorkspaceToolConfig]:
    normalized = _normalize_tool_configs(configs)
    _write_tool_configs(normalized)
    return normalized


@router.get("/mcp", response_model=list[WorkspaceMcpServerConfig])
def list_mcp_server_configs() -> list[WorkspaceMcpServerConfig]:
    return _read_mcp_server_configs()


@router.put("/mcp", response_model=list[WorkspaceMcpServerConfig])
def save_mcp_server_configs(configs: list[WorkspaceMcpServerConfig]) -> list[WorkspaceMcpServerConfig]:
    normalized = _normalize_mcp_server_configs(configs)
    _write_mcp_server_configs(normalized)
    return normalized


@router.get("/models", response_model=list[WorkspaceModelConfig])
def list_model_configs() -> list[WorkspaceModelConfig]:
    return _read_model_configs()


@router.put("/models", response_model=list[WorkspaceModelConfig])
def save_model_configs(configs: list[WorkspaceModelConfig]) -> list[WorkspaceModelConfig]:
    normalized = _normalize_model_configs(configs)
    _write_model_configs(normalized)
    return normalized


@router.get("/rag", response_model=list[WorkspaceRagKnowledgeBase])
def list_rag_knowledge_bases() -> list[WorkspaceRagKnowledgeBase]:
    return _read_rag_knowledge_bases()


@router.put("/rag", response_model=list[WorkspaceRagKnowledgeBase])
def save_rag_knowledge_bases(items: list[WorkspaceRagKnowledgeBase]) -> list[WorkspaceRagKnowledgeBase]:
    normalized = _normalize_rag_knowledge_bases(items)
    _write_rag_knowledge_bases(normalized)
    return normalized


@router.post("/rag/inspect", response_model=RagPathInspectResult)
def inspect_rag_path(payload: RagPathInspectRequest) -> RagPathInspectResult:
    raw_path = payload.path.strip().strip('"')
    if not raw_path:
        raise HTTPException(status_code=400, detail="请先输入 RAG 知识库路径。")

    input_path = Path(raw_path).expanduser()
    warnings: list[str] = []
    detected_files: list[str] = []
    if not input_path.exists():
        return RagPathInspectResult(
            exists=False,
            path=raw_path,
            warnings=[f"路径不存在：{raw_path}"],
        )

    if input_path.is_file():
        scan_root = input_path.parent
        source_type = "local_files"
        detected_files.append(str(input_path))
    else:
        scan_root = input_path
        source_type = "local_directory"

    chroma_root = _find_chroma_root(scan_root)
    if chroma_root:
        source_type = "vectorstore"
        result_path = str(chroma_root)
        detected_files.append(str(chroma_root / "chroma.sqlite3"))
    else:
        result_path = str(input_path)

    hints, hint_files = _read_rag_runtime_hints(chroma_root or scan_root, scan_root)
    detected_files.extend(hint_files)
    collection = _first_non_empty(
        hints.get("collection"),
        hints.get("collectionName"),
        hints.get("COLLECTION_NAME"),
        hints.get("index"),
        hints.get("indexName"),
    )
    if chroma_root and not collection:
        collection = _read_chroma_collection_name(chroma_root / "chroma.sqlite3")

    embedding_model = _first_non_empty(hints.get("embeddingModel"), hints.get("embedding_model"), hints.get("EMBEDDING_MODEL"))
    top_k = _positive_int(_first_non_empty(hints.get("topK"), hints.get("top_k"), hints.get("TOP_K")), 4)
    metadata = _rag_metadata_from_hints(hints, collection, warnings)
    description = _describe_rag_path(source_type, input_path, chroma_root, collection, embedding_model, top_k)

    return RagPathInspectResult(
        exists=True,
        sourceType=source_type,
        path=result_path,
        collection=collection,
        description=description,
        embeddingModel=embedding_model,
        topK=top_k,
        metadataJson=json.dumps(metadata, ensure_ascii=False, indent=2) if metadata else "{}",
        detectedFiles=_dedupe_strings(detected_files),
        warnings=warnings,
    )


def _read_tool_configs() -> list[WorkspaceToolConfig]:
    ensure_runtime_dirs()
    if not WORKSPACE_TOOLS_FILE.exists():
        return []
    try:
        raw = json.loads(WORKSPACE_TOOLS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(raw, list):
        return []
    return _normalize_tool_configs([WorkspaceToolConfig.model_validate(item) for item in raw if isinstance(item, dict)])


def _write_tool_configs(configs: list[WorkspaceToolConfig]) -> None:
    _write_workspace_list(WORKSPACE_TOOLS_FILE, [config.model_dump(by_alias=True) for config in configs])


def _read_mcp_server_configs() -> list[WorkspaceMcpServerConfig]:
    ensure_runtime_dirs()
    if not WORKSPACE_MCP_FILE.exists():
        return []
    try:
        raw = json.loads(WORKSPACE_MCP_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(raw, list):
        return []
    return _normalize_mcp_server_configs([WorkspaceMcpServerConfig.model_validate(item) for item in raw if isinstance(item, dict)])


def _write_mcp_server_configs(configs: list[WorkspaceMcpServerConfig]) -> None:
    _write_workspace_list(WORKSPACE_MCP_FILE, [config.model_dump(by_alias=True) for config in configs])


def _read_model_configs() -> list[WorkspaceModelConfig]:
    ensure_runtime_dirs()
    if not WORKSPACE_MODELS_FILE.exists():
        return []
    try:
        raw = json.loads(WORKSPACE_MODELS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(raw, list):
        return []
    return _normalize_model_configs([WorkspaceModelConfig.model_validate(item) for item in raw if isinstance(item, dict)])


def _write_model_configs(configs: list[WorkspaceModelConfig]) -> None:
    _write_workspace_list(WORKSPACE_MODELS_FILE, [config.model_dump(by_alias=True) for config in configs])


def _read_rag_knowledge_bases() -> list[WorkspaceRagKnowledgeBase]:
    ensure_runtime_dirs()
    if not WORKSPACE_RAG_FILE.exists():
        return []
    try:
        raw = json.loads(WORKSPACE_RAG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(raw, list):
        return []
    return _normalize_rag_knowledge_bases([WorkspaceRagKnowledgeBase.model_validate(item) for item in raw if isinstance(item, dict)])


def _write_rag_knowledge_bases(items: list[WorkspaceRagKnowledgeBase]) -> None:
    _write_workspace_list(WORKSPACE_RAG_FILE, [item.model_dump(by_alias=True) for item in items])


def _write_workspace_list(path, payload: list[dict]) -> None:
    ensure_runtime_dirs()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".json.tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(path)


def _normalize_tool_configs(configs: list[WorkspaceToolConfig]) -> list[WorkspaceToolConfig]:
    normalized: list[WorkspaceToolConfig] = []
    for config in configs:
        normalized.append(
            config.model_copy(
                update={
                    "id": config.id.strip() or f"tool_{uuid4().hex[:8]}",
                    "name": config.name.strip() or "未命名工具",
                    "source": config.source.strip() or "python",
                    "tool_schema": config.tool_schema.strip() or "{}",
                },
            ),
        )
    return normalized


def _normalize_mcp_server_configs(configs: list[WorkspaceMcpServerConfig]) -> list[WorkspaceMcpServerConfig]:
    normalized: list[WorkspaceMcpServerConfig] = []
    for config in configs:
        normalized.append(
            config.model_copy(
                update={
                    "id": config.id.strip() or f"mcp_{uuid4().hex[:8]}",
                    "name": config.name.strip() or "未命名 MCP",
                    "transport": config.transport.strip() or "stdio",
                    "command": config.command.strip(),
                    "url": config.url.strip(),
                },
            ),
        )
    return normalized


def _normalize_model_configs(configs: list[WorkspaceModelConfig]) -> list[WorkspaceModelConfig]:
    normalized: list[WorkspaceModelConfig] = []
    default_assigned = False
    any_default = any(config.is_default for config in configs)
    for index, config in enumerate(configs):
        is_default = not default_assigned and (config.is_default or (not any_default and index == 0))
        if is_default:
            default_assigned = True
        normalized.append(
            config.model_copy(
                update={
                    "id": config.id.strip() or f"model_{uuid4().hex[:8]}",
                    "name": config.name.strip() or "未命名模型配置",
                    "provider": config.provider.strip() or "openai",
                    "model": config.model.strip(),
                    "api_key": "",
                    "api_key_env": _safe_env_name(config.api_key_env),
                    "is_default": is_default,
                },
            ),
        )
    return normalized


def _safe_env_name(value: str) -> str:
    text = value.strip()
    return text if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", text) else ""


def _normalize_rag_knowledge_bases(items: list[WorkspaceRagKnowledgeBase]) -> list[WorkspaceRagKnowledgeBase]:
    normalized: list[WorkspaceRagKnowledgeBase] = []
    for item in items:
        normalized.append(
            item.model_copy(
                update={
                    "id": item.id.strip() or f"rag_{uuid4().hex[:8]}",
                    "name": item.name.strip() or "未命名知识库",
                    "source_type": item.source_type.strip() or "local_directory",
                    "path": item.path.strip(),
                    "url": item.url.strip(),
                    "collection": item.collection.strip(),
                    "top_k": max(1, item.top_k or 4),
                    "metadata_json": item.metadata_json.strip() or "{}",
                },
            )
        )
    return normalized


def _find_chroma_root(root: Path) -> Path | None:
    if (root / "chroma.sqlite3").is_file():
        return root
    for child in sorted(root.iterdir(), key=lambda item: item.name.lower()):
        if child.is_dir() and (child / "chroma.sqlite3").is_file():
            return child
    try:
        for sqlite_path in root.rglob("chroma.sqlite3"):
            if sqlite_path.is_file():
                return sqlite_path.parent
    except OSError:
        return None
    return None


def _read_rag_runtime_hints(root: Path, original_root: Path) -> tuple[dict[str, Any], list[str]]:
    hints: dict[str, Any] = {}
    detected_files: list[str] = []
    candidates = [
        root / "runtime_config.json",
        root.parent / "runtime_config.json",
        original_root / "runtime_config.json",
    ]
    for path in candidates:
        if not path.exists() or not path.is_file():
            continue
        data = _read_json_object(path)
        if data:
            for key, value in data.items():
                hints.setdefault(key, value)
            detected_files.append(str(path))
    return hints, _dedupe_strings(detected_files)


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _read_chroma_collection_name(sqlite_path: Path) -> str:
    if not sqlite_path.exists():
        return ""
    try:
        with sqlite3.connect(str(sqlite_path)) as connection:
            row = connection.execute("SELECT name FROM collections ORDER BY name LIMIT 1").fetchone()
    except sqlite3.Error:
        return ""
    return str(row[0]) if row and row[0] else ""


def _rag_metadata_from_hints(hints: dict[str, Any], collection: str, warnings: list[str]) -> dict[str, str]:
    metadata: dict[str, str] = {}
    base_url = _first_non_empty(
        hints.get("embeddingBaseUrl"),
        hints.get("embeddingApiBase"),
        hints.get("EMBEDDING_API_BASE"),
        hints.get("baseUrl"),
        hints.get("apiBase"),
    )
    api_key_env = _first_non_empty(hints.get("embeddingApiKeyEnv"), hints.get("apiKeyEnv"), hints.get("EMBEDDING_API_KEY_ENV"))
    has_direct_key = any(
        _first_non_empty(hints.get(key))
        for key in ("embeddingApiKey", "apiKey", "EMBEDDING_API_KEY", "DASHSCOPE_API_KEY")
    )
    if base_url:
        metadata["embeddingBaseUrl"] = base_url
    if api_key_env:
        metadata["embeddingApiKeyEnv"] = api_key_env
    elif has_direct_key:
        metadata["embeddingApiKeyEnv"] = "EMBEDDING_API_KEY"
        warnings.append("检测到 runtime_config.json 中存在明文 embedding key，已从元数据中排除；建议改用 EMBEDDING_API_KEY 环境变量。")
    if collection:
        metadata["collection"] = collection
    return metadata


def _describe_rag_path(source_type: str, input_path: Path, chroma_root: Path | None, collection: str, embedding_model: str, top_k: int) -> str:
    if source_type == "vectorstore":
        detail = [f"检测到 Chroma 向量库：{chroma_root or input_path}"]
        if collection:
            detail.append(f"collection={collection}")
        if embedding_model:
            detail.append(f"embedding={embedding_model}")
        detail.append(f"topK={top_k}")
        return "；".join(detail)
    if input_path.is_file():
        return f"检测到本地文件：{input_path.name}"
    text_count = _count_text_files(input_path)
    return f"检测到本地目录：{input_path}；文本文件 {text_count} 个"


def _count_text_files(root: Path) -> int:
    suffixes = {".txt", ".md", ".markdown", ".json", ".jsonl", ".csv", ".tsv"}
    try:
        return sum(1 for path in root.rglob("*") if path.is_file() and path.suffix.lower() in suffixes)
    except OSError:
        return 0


def _first_non_empty(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _positive_int(value: Any, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback


def _dedupe_strings(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
