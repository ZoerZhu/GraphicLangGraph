from __future__ import annotations

import json
from uuid import uuid4

from fastapi import APIRouter
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
                    "is_default": is_default,
                },
            ),
        )
    return normalized


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
