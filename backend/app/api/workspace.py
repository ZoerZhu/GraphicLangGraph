from __future__ import annotations

import ast
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tomllib
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from app.config import (
    CONFIG_MCP_DIR,
    CONFIG_SKILLS_DIR,
    CONFIG_TOOLS_DIR,
    WORKSPACE_MCP_FILE,
    WORKSPACE_MODELS_FILE,
    WORKSPACE_RAG_FILE,
    WORKSPACE_SKILLS_FILE,
    WORKSPACE_TOOLS_FILE,
    ensure_runtime_dirs,
    load_runtime_env,
)


router = APIRouter(prefix="/api/workspace", tags=["workspace"])


class WorkspaceToolConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    id: str = Field(default_factory=lambda: f"tool_{uuid4().hex[:8]}")
    name: str = "未命名工具"
    description: str = ""
    source: str = "python"
    tool_schema: str = Field("{}", alias="schemaJson")


class WorkspaceSkillConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    id: str = Field(default_factory=lambda: f"skill_{uuid4().hex[:8]}")
    name: str = "未命名 Skill"
    description: str = ""
    source_type: str = Field("manual", alias="sourceType")
    source_path: str = Field("", alias="sourcePath")
    file_path: str = Field("", alias="filePath")
    content: str = ""
    metadata_json: str = Field("{}", alias="metadataJson")
    enabled: bool = True


class WorkspaceMcpServerConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    id: str = Field(default_factory=lambda: f"mcp_{uuid4().hex[:8]}")
    name: str = "未命名 MCP"
    transport: str = "stdio"
    command: str = ""
    args_json: str = Field("[]", alias="argsJson")
    env_json: str = Field("{}", alias="envJson")
    env_vars_json: str = Field("[]", alias="envVarsJson")
    cwd: str = ""
    url: str = ""
    bearer_token_env_var: str = Field("", alias="bearerTokenEnvVar")
    http_headers_json: str = Field("{}", alias="httpHeadersJson")
    env_http_headers_json: str = Field("{}", alias="envHttpHeadersJson")
    enabled: bool = True
    startup_timeout_sec: int = Field(10, alias="startupTimeoutSec")
    tool_timeout_sec: int = Field(60, alias="toolTimeoutSec")
    enabled_tools_json: str = Field("[]", alias="enabledToolsJson")
    disabled_tools_json: str = Field("[]", alias="disabledToolsJson")
    default_tools_approval_mode: str = Field("", alias="defaultToolsApprovalMode")
    source_type: str = Field("manual", alias="sourceType")
    source_path: str = Field("", alias="sourcePath")
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
    api_key_mode: str = Field("env", alias="apiKeyMode")
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


class EnvVarCheckRequest(BaseModel):
    name: str


class EnvVarCheckResponse(BaseModel):
    valid: bool
    exists: bool
    name: str
    length: int = 0
    message: str = ""


class McpImportRequest(BaseModel):
    source_type: str = Field("local", alias="sourceType")
    source: str
    use_mirror: bool = Field(True, alias="useMirror")


class ToolImportRequest(BaseModel):
    source_type: str = Field("local", alias="sourceType")
    source: str
    use_mirror: bool = Field(True, alias="useMirror")


class SkillImportRequest(BaseModel):
    source_type: str = Field("local", alias="sourceType")
    source: str
    use_mirror: bool = Field(True, alias="useMirror")


class ToolImportResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    imported: list[WorkspaceToolConfig]
    all_configs: list[WorkspaceToolConfig] = Field(alias="allConfigs")
    import_path: str = Field("", alias="importPath")
    detected_files: list[str] = Field(default_factory=list, alias="detectedFiles")
    warnings: list[str] = Field(default_factory=list)


class SkillImportResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    imported: list[WorkspaceSkillConfig]
    all_configs: list[WorkspaceSkillConfig] = Field(alias="allConfigs")
    import_path: str = Field("", alias="importPath")
    detected_files: list[str] = Field(default_factory=list, alias="detectedFiles")
    warnings: list[str] = Field(default_factory=list)


class McpImportResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    imported: list[WorkspaceMcpServerConfig]
    all_configs: list[WorkspaceMcpServerConfig] = Field(alias="allConfigs")
    import_path: str = Field("", alias="importPath")
    detected_files: list[str] = Field(default_factory=list, alias="detectedFiles")
    warnings: list[str] = Field(default_factory=list)


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


@router.post("/tools/import", response_model=ToolImportResponse)
def import_tool_configs(payload: ToolImportRequest) -> ToolImportResponse:
    source_type = payload.source_type.strip().lower()
    source = payload.source.strip().strip('"')
    if source_type not in {"local", "github"}:
        raise HTTPException(status_code=400, detail="导入类型只支持 local 或 github。")
    if not source:
        raise HTTPException(status_code=400, detail="请提供本地路径或 GitHub 地址。")

    warnings: list[str] = []
    if source_type == "github":
        import_root = _clone_tool_repository(source, payload.use_mirror, warnings)
    else:
        import_root = _copy_local_tool_source(source, warnings)

    imported, detected_files, detect_warnings = _detect_tool_configs(import_root, source_type)
    warnings.extend(detect_warnings)
    if not imported:
        raise HTTPException(status_code=422, detail="未识别到工具。请确认目录内存在 Python @tool 函数、OpenAPI spec 或 tools.json。")

    existing = _read_tool_configs()
    merged = _merge_tool_configs(existing, imported)
    _write_tool_configs(merged)
    return ToolImportResponse(
        imported=imported,
        allConfigs=merged,
        importPath=str(import_root),
        detectedFiles=detected_files,
        warnings=warnings,
    )


@router.post("/tools/upload", response_model=ToolImportResponse)
async def upload_tool_folder(
    files: list[UploadFile] = File(...),
    root_name: str = Form("uploaded-tools", alias="rootName"),
) -> ToolImportResponse:
    if not files:
        raise HTTPException(status_code=400, detail="请选择要上传的本地文件夹。")

    warnings: list[str] = []
    import_root = _unique_tool_import_path(_slugify(root_name or "uploaded-tools"))
    import_root.mkdir(parents=True, exist_ok=True)
    saved_files: list[str] = []
    for upload in files:
        relative = _safe_uploaded_relative_path(upload.filename)
        if not relative:
            continue
        relative = _strip_uploaded_root(relative, root_name)
        if _should_skip_import_path(Path(relative.as_posix())):
            continue
        target = import_root / Path(*relative.parts)
        if not _is_relative_to(target.resolve(), import_root.resolve()):
            warnings.append(f"已跳过不安全路径：{upload.filename}")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        content = await upload.read()
        target.write_bytes(content)
        saved_files.append(str(target))

    if not saved_files:
        shutil.rmtree(import_root, ignore_errors=True)
        raise HTTPException(status_code=400, detail="上传文件夹中没有可导入的文件。")

    imported, detected_files, detect_warnings = _detect_tool_configs(import_root, "upload")
    warnings.extend(detect_warnings)
    if not imported:
        raise HTTPException(status_code=422, detail="上传完成，但未识别到工具。请确认存在 Python @tool 函数、OpenAPI spec 或 tools.json。")

    existing = _read_tool_configs()
    merged = _merge_tool_configs(existing, imported)
    _write_tool_configs(merged)
    return ToolImportResponse(
        imported=imported,
        allConfigs=merged,
        importPath=str(import_root),
        detectedFiles=_dedupe_strings([*saved_files, *detected_files]),
        warnings=warnings,
    )


@router.get("/skills", response_model=list[WorkspaceSkillConfig])
def list_skill_configs() -> list[WorkspaceSkillConfig]:
    return _read_skill_configs()


@router.put("/skills", response_model=list[WorkspaceSkillConfig])
def save_skill_configs(configs: list[WorkspaceSkillConfig]) -> list[WorkspaceSkillConfig]:
    normalized = _normalize_skill_configs(configs)
    _write_skill_configs(normalized)
    return normalized


@router.post("/skills/import", response_model=SkillImportResponse)
def import_skill_configs(payload: SkillImportRequest) -> SkillImportResponse:
    source_type = payload.source_type.strip().lower()
    source = payload.source.strip().strip('"')
    if source_type not in {"local", "github"}:
        raise HTTPException(status_code=400, detail="导入类型只支持 local 或 github。")
    if not source:
        raise HTTPException(status_code=400, detail="请提供本地路径或 GitHub 地址。")

    warnings: list[str] = []
    if source_type == "github":
        import_root = _clone_skill_repository(source, payload.use_mirror, warnings)
    else:
        import_root = _copy_local_skill_source(source, warnings)

    imported, detected_files, detect_warnings = _detect_skill_configs(import_root, source_type)
    warnings.extend(detect_warnings)
    if not imported:
        raise HTTPException(status_code=422, detail="未识别到 Skill。请确认目录中存在 SKILL.md 或普通 Markdown 文件。")

    existing = _read_skill_configs()
    merged = _merge_skill_configs(existing, imported)
    _write_skill_configs(merged)
    return SkillImportResponse(
        imported=imported,
        allConfigs=merged,
        importPath=str(import_root),
        detectedFiles=detected_files,
        warnings=warnings,
    )


@router.post("/skills/upload", response_model=SkillImportResponse)
async def upload_skill_folder(
    files: list[UploadFile] = File(...),
    root_name: str = Form("uploaded-skills", alias="rootName"),
) -> SkillImportResponse:
    if not files:
        raise HTTPException(status_code=400, detail="请选择要上传的本地 Skill 文件或文件夹。")

    warnings: list[str] = []
    import_root = _unique_skill_import_path(_slugify(root_name or "uploaded-skills"))
    import_root.mkdir(parents=True, exist_ok=True)
    saved_files: list[str] = []
    for upload in files:
        relative = _safe_uploaded_relative_path(upload.filename)
        if not relative:
            continue
        relative = _strip_uploaded_root(relative, root_name)
        if _should_skip_import_path(Path(relative.as_posix())):
            continue
        target = import_root / Path(*relative.parts)
        if not _is_relative_to(target.resolve(), import_root.resolve()):
            warnings.append(f"已跳过不安全路径：{upload.filename}")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        content = await upload.read()
        target.write_bytes(content)
        saved_files.append(str(target))

    if not saved_files:
        shutil.rmtree(import_root, ignore_errors=True)
        raise HTTPException(status_code=400, detail="上传内容中没有可导入的文件。")

    imported, detected_files, detect_warnings = _detect_skill_configs(import_root, "upload")
    warnings.extend(detect_warnings)
    if not imported:
        raise HTTPException(status_code=422, detail="上传完成，但未识别到 Skill。请确认存在 SKILL.md 或 Markdown 文件。")

    existing = _read_skill_configs()
    merged = _merge_skill_configs(existing, imported)
    _write_skill_configs(merged)
    return SkillImportResponse(
        imported=imported,
        allConfigs=merged,
        importPath=str(import_root),
        detectedFiles=_dedupe_strings([*saved_files, *detected_files]),
        warnings=warnings,
    )


@router.get("/mcp", response_model=list[WorkspaceMcpServerConfig])
def list_mcp_server_configs() -> list[WorkspaceMcpServerConfig]:
    return _read_mcp_server_configs()


@router.put("/mcp", response_model=list[WorkspaceMcpServerConfig])
def save_mcp_server_configs(configs: list[WorkspaceMcpServerConfig]) -> list[WorkspaceMcpServerConfig]:
    normalized = _normalize_mcp_server_configs(configs)
    _write_mcp_server_configs(normalized)
    return normalized


@router.post("/mcp/import", response_model=McpImportResponse)
def import_mcp_server_configs(payload: McpImportRequest) -> McpImportResponse:
    source_type = payload.source_type.strip().lower()
    source = payload.source.strip().strip('"')
    if source_type not in {"local", "github"}:
        raise HTTPException(status_code=400, detail="导入类型只支持 local 或 github。")
    if not source:
        raise HTTPException(status_code=400, detail="请提供本地路径或 GitHub 地址。")

    warnings: list[str] = []
    if source_type == "github":
        import_root = _clone_mcp_repository(source, payload.use_mirror, warnings)
    else:
        import_root = _copy_local_mcp_source(source, warnings)

    imported, detected_files, detect_warnings = _detect_mcp_server_configs(import_root, source_type)
    warnings.extend(detect_warnings)
    if not imported:
        raise HTTPException(status_code=422, detail="未识别到 MCP 配置。请确认存在 Codex config.toml、mcp.json、package.json 或 .codex/config.toml。")

    existing = _read_mcp_server_configs()
    merged = _merge_mcp_server_configs(existing, imported)
    _write_mcp_server_configs(merged)
    return McpImportResponse(
        imported=imported,
        allConfigs=merged,
        importPath=str(import_root),
        detectedFiles=detected_files,
        warnings=warnings,
    )


@router.get("/models", response_model=list[WorkspaceModelConfig])
def list_model_configs() -> list[WorkspaceModelConfig]:
    return _read_model_configs()


@router.put("/models", response_model=list[WorkspaceModelConfig])
def save_model_configs(configs: list[WorkspaceModelConfig]) -> list[WorkspaceModelConfig]:
    normalized = _normalize_model_configs(configs)
    _write_model_configs(normalized)
    return normalized


@router.post("/env/check", response_model=EnvVarCheckResponse)
def check_env_var(payload: EnvVarCheckRequest) -> EnvVarCheckResponse:
    load_runtime_env()
    name = payload.name.strip()
    if not _is_env_name(name):
        return EnvVarCheckResponse(
            valid=False,
            exists=False,
            name=name,
            message="环境变量名格式不正确，应类似 MIMO_API_KEY。",
        )
    value = os.getenv(name, "").strip()
    if value:
        return EnvVarCheckResponse(
            valid=True,
            exists=True,
            name=name,
            length=len(value),
            message=f"已读取到 {name}，长度 {len(value)}。",
        )
    return EnvVarCheckResponse(
        valid=True,
        exists=False,
        name=name,
        message=f"未读取到 {name}。请确认 .env 位置或重启后端。",
    )


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


def _copy_local_tool_source(source: str, warnings: list[str]) -> Path:
    ensure_runtime_dirs()
    source_path = Path(source).expanduser().resolve()
    if not source_path.exists():
        raise HTTPException(status_code=400, detail=f"本地路径不存在：{source}")

    destination = _unique_tool_import_path(_slugify(source_path.stem if source_path.is_file() else source_path.name))
    if source_path.is_file():
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination / source_path.name)
    else:
        if _is_relative_to(source_path, CONFIG_TOOLS_DIR.resolve()):
            warnings.append("导入源已位于 config/tools 下，直接复用该目录。")
            return source_path
        shutil.copytree(source_path, destination, ignore=_ignore_import_files)
    return destination


def _clone_tool_repository(source: str, use_mirror: bool, warnings: list[str]) -> Path:
    ensure_runtime_dirs()
    repo_slug = _github_repo_slug(source)
    if not repo_slug:
        raise HTTPException(status_code=400, detail="请提供有效的 GitHub 仓库地址，例如 https://github.com/org/repo。")
    destination = _unique_tool_import_path(repo_slug.replace("/", "__"))
    urls = _github_clone_candidates(source, use_mirror)
    errors: list[str] = []
    for url in urls:
        try:
            subprocess.run(
                ["git", "clone", "--depth", "1", url, str(destination)],
                check=True,
                capture_output=True,
                text=True,
                timeout=180,
            )
            if url != source:
                warnings.append(f"已通过 GitHub 镜像源 clone：{url}")
            return destination
        except (subprocess.SubprocessError, OSError) as error:
            if destination.exists():
                shutil.rmtree(destination, ignore_errors=True)
            errors.append(str(error))
    raise HTTPException(status_code=502, detail=f"GitHub 仓库 clone 失败：{'; '.join(errors[-2:])}")


def _detect_tool_configs(root: Path, source_type: str) -> tuple[list[WorkspaceToolConfig], list[str], list[str]]:
    detected_files: list[str] = []
    warnings: list[str] = []
    configs: list[WorkspaceToolConfig] = []

    for path in _candidate_tool_config_files(root):
        detected_files.append(str(path))
        if path.suffix.lower() == ".py":
            configs.extend(_read_tool_configs_from_python(path, root, source_type, warnings))
        elif path.suffix.lower() == ".json":
            configs.extend(_read_tool_configs_from_json(path, root, source_type, warnings))

    return _normalize_tool_configs(_dedupe_tool_configs(configs)), _dedupe_strings(detected_files), warnings


def _candidate_tool_config_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root] if root.suffix.lower() in {".py", ".json"} else []

    priority_names = {
        "tools.json",
        "tool.json",
        "openapi.json",
        "swagger.json",
        "api.json",
    }
    result: list[Path] = []
    for name in priority_names:
        path = root / name
        if path.is_file():
            result.append(path)
    try:
        for path in root.rglob("*"):
            if len(result) >= 240:
                break
            if not path.is_file() or _should_skip_import_path(path) or path in result:
                continue
            suffix = path.suffix.lower()
            if suffix == ".py":
                result.append(path)
            elif suffix == ".json" and _looks_like_tool_json(path):
                result.append(path)
    except OSError:
        pass
    return result


def _looks_like_tool_json(path: Path) -> bool:
    name = path.name.lower()
    if any(key in name for key in ("tool", "openapi", "swagger", "api")):
        return True
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")[:4000]
    except OSError:
        return False
    return any(token in text for token in ('"tools"', '"openapi"', '"swagger"', '"operationId"'))


def _read_tool_configs_from_python(path: Path, root: Path, source_type: str, warnings: list[str]) -> list[WorkspaceToolConfig]:
    try:
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
    except (OSError, SyntaxError, UnicodeDecodeError) as error:
        warnings.append(f"Python 工具解析失败：{path}：{error}")
        return []

    functions = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    decorated_count = sum(1 for node in functions if _tool_decorator_name(node))
    include_public_typed = decorated_count == 0 and _looks_like_tool_python_file(path)
    configs: list[WorkspaceToolConfig] = []
    for node in functions:
        if node.name.startswith("_"):
            continue
        decorator_name = _tool_decorator_name(node)
        if not decorator_name and not (include_public_typed and _looks_like_tool_function(node)):
            continue
        tool_name = _python_tool_name(node) or node.name
        description = _first_doc_line(ast.get_docstring(node) or "") or f"从 {path.name} 自动识别的 Python 工具"
        relative = _relative_import_path(path, root)
        schema = {
            "type": "object",
            "properties": _python_function_properties(node),
            "required": _python_function_required_args(node),
            "x-graphic": {
                "kind": "python_function",
                "sourceType": source_type,
                "sourcePath": str(path),
                "relativePath": relative,
                "function": node.name,
                "entrypoint": f"{_module_path_from_relative(relative)}:{node.name}",
                "decorator": decorator_name,
                "async": isinstance(node, ast.AsyncFunctionDef),
                "returnType": _annotation_to_text(node.returns),
            },
        }
        configs.append(
            WorkspaceToolConfig(
                id=f"tool_{_slugify(tool_name)}_{uuid4().hex[:6]}",
                name=tool_name,
                description=description,
                source="python",
                schemaJson=_json_dumps(schema),
            )
        )
    return configs


def _read_tool_configs_from_json(path: Path, root: Path, source_type: str, warnings: list[str]) -> list[WorkspaceToolConfig]:
    data = _read_json_object(path)
    if not data:
        return []
    if "openapi" in data or "swagger" in data:
        return _read_tool_configs_from_openapi(path, root, data, source_type)
    raw_tools = data.get("tools")
    if isinstance(raw_tools, dict):
        raw_tools = [{"name": key, **value} if isinstance(value, dict) else {"name": key, "description": str(value)} for key, value in raw_tools.items()]
    if not isinstance(raw_tools, list):
        return []

    configs: list[WorkspaceToolConfig] = []
    for index, raw in enumerate(raw_tools):
        if not isinstance(raw, dict):
            continue
        name = _first_non_empty(raw.get("name"), raw.get("id"), f"{path.stem}_{index + 1}")
        schema_value = raw.get("schema") or raw.get("parameters") or raw.get("argsSchema") or raw.get("inputSchema") or {}
        schema = schema_value if isinstance(schema_value, dict) else {}
        schema.setdefault("type", "object")
        schema.setdefault("properties", {})
        schema["x-graphic"] = {
            **(schema.get("x-graphic") if isinstance(schema.get("x-graphic"), dict) else {}),
            "kind": "json_tool",
            "sourceType": source_type,
            "sourcePath": str(path),
            "relativePath": _relative_import_path(path, root),
        }
        configs.append(
            WorkspaceToolConfig(
                id=f"tool_{_slugify(name)}_{uuid4().hex[:6]}",
                name=name,
                description=_first_non_empty(raw.get("description"), raw.get("summary"), f"从 {path.name} 导入"),
                source=_first_non_empty(raw.get("source"), "json"),
                schemaJson=_json_dumps(schema),
            )
        )
    return configs


def _read_tool_configs_from_openapi(path: Path, root: Path, data: dict[str, Any], source_type: str) -> list[WorkspaceToolConfig]:
    paths = data.get("paths")
    if not isinstance(paths, dict):
        return []
    configs: list[WorkspaceToolConfig] = []
    for route, operations in paths.items():
        if not isinstance(operations, dict):
            continue
        for method, operation in operations.items():
            method_key = str(method).lower()
            if method_key not in {"get", "post", "put", "patch", "delete"} or not isinstance(operation, dict):
                continue
            name = _first_non_empty(operation.get("operationId"), f"{method_key}_{route}")
            schema = _openapi_operation_schema(operation)
            schema["x-graphic"] = {
                "kind": "openapi_operation",
                "sourceType": source_type,
                "sourcePath": str(path),
                "relativePath": _relative_import_path(path, root),
                "method": method_key.upper(),
                "path": str(route),
            }
            configs.append(
                WorkspaceToolConfig(
                    id=f"tool_{_slugify(name)}_{uuid4().hex[:6]}",
                    name=_slugify(name),
                    description=_first_non_empty(operation.get("summary"), operation.get("description"), f"{method_key.upper()} {route}"),
                    source="openapi",
                    schemaJson=_json_dumps(schema),
                )
            )
    return configs


def _openapi_operation_schema(operation: dict[str, Any]) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    required: list[str] = []
    parameters = operation.get("parameters") if isinstance(operation.get("parameters"), list) else []
    for parameter in parameters:
        if not isinstance(parameter, dict):
            continue
        name = _first_non_empty(parameter.get("name"))
        if not name:
            continue
        schema = parameter.get("schema") if isinstance(parameter.get("schema"), dict) else {"type": "string"}
        properties[name] = {**schema, "description": _first_non_empty(parameter.get("description"), parameter.get("in"))}
        if parameter.get("required") is True:
            required.append(name)
    request_body = operation.get("requestBody")
    if isinstance(request_body, dict):
        body_schema = _openapi_request_body_schema(request_body)
        if body_schema:
            properties["body"] = body_schema
            required.append("body")
    return {"type": "object", "properties": properties, "required": _dedupe_strings(required)}


def _openapi_request_body_schema(request_body: dict[str, Any]) -> dict[str, Any]:
    content = request_body.get("content")
    if not isinstance(content, dict):
        return {}
    for media_type in ("application/json", "application/x-www-form-urlencoded", "multipart/form-data"):
        media = content.get(media_type)
        if isinstance(media, dict) and isinstance(media.get("schema"), dict):
            return media["schema"]
    for media in content.values():
        if isinstance(media, dict) and isinstance(media.get("schema"), dict):
            return media["schema"]
    return {}


def _tool_decorator_name(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    for decorator in node.decorator_list:
        name = _decorator_qualified_name(decorator)
        if name and any(token in name.lower() for token in ("tool", "function_tool")):
            return name
    return ""


def _decorator_qualified_name(node: ast.AST) -> str:
    if isinstance(node, ast.Call):
        return _decorator_qualified_name(node.func)
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _decorator_qualified_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def _python_tool_name(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        name = _decorator_qualified_name(decorator.func)
        if not name or "tool" not in name.lower():
            continue
        if decorator.args and isinstance(decorator.args[0], ast.Constant) and isinstance(decorator.args[0].value, str):
            return decorator.args[0].value.strip()
        for keyword in decorator.keywords:
            if keyword.arg in {"name", "tool_name"} and isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
                return keyword.value.value.strip()
    return node.name


def _looks_like_tool_python_file(path: Path) -> bool:
    parts = {part.lower() for part in path.parts}
    return "tools" in parts or "tool" in path.stem.lower()


def _looks_like_tool_function(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    if not ast.get_docstring(node):
        return False
    args = node.args.args + node.args.kwonlyargs
    if not args:
        return True
    return any(arg.annotation is not None for arg in args) or node.returns is not None


def _python_function_properties(node: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, dict[str, Any]]:
    properties: dict[str, dict[str, Any]] = {}
    args = [arg for arg in node.args.args if arg.arg not in {"self", "cls"}]
    for arg in [*args, *node.args.kwonlyargs]:
        properties[arg.arg] = {"type": _json_type_from_annotation(arg.annotation)}
    return properties


def _python_function_required_args(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    positional = [arg.arg for arg in node.args.args if arg.arg not in {"self", "cls"}]
    defaults = node.args.defaults
    optional = set(positional[-len(defaults) :]) if defaults else set()
    required = [name for name in positional if name not in optional]
    for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults):
        if default is None:
            required.append(arg.arg)
    return required


def _json_type_from_annotation(annotation: ast.AST | None) -> str:
    text = _annotation_to_text(annotation).lower()
    if text in {"int", "float"}:
        return "number"
    if text in {"bool", "boolean"}:
        return "boolean"
    if text in {"dict", "mapping"} or text.startswith("dict["):
        return "object"
    if text in {"list", "tuple", "set"} or text.startswith(("list[", "tuple[", "set[")):
        return "array"
    return "string"


def _annotation_to_text(annotation: ast.AST | None) -> str:
    if annotation is None:
        return ""
    try:
        return ast.unparse(annotation)
    except Exception:
        return ""


def _first_doc_line(value: str) -> str:
    for line in value.splitlines():
        text = line.strip()
        if text:
            return text
    return ""


def _relative_import_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name


def _module_path_from_relative(relative_path: str) -> str:
    if relative_path.endswith(".py"):
        relative_path = relative_path[:-3]
    parts = [part for part in PurePosixPath(relative_path).parts if part != "__init__"]
    return ".".join(_slugify(part).replace("-", "_") for part in parts if part)


def _merge_tool_configs(existing: list[WorkspaceToolConfig], imported: list[WorkspaceToolConfig]) -> list[WorkspaceToolConfig]:
    merged = [*existing]
    for item in imported:
        base_name = item.name
        candidate = item
        suffix = 2
        existing_names = {config.name.lower() for config in merged}
        while candidate.name.lower() in existing_names:
            candidate = candidate.model_copy(update={"name": f"{base_name} {suffix}", "id": f"{item.id}_{suffix}"})
            suffix += 1
        merged.append(candidate)
    return _normalize_tool_configs(merged)


def _dedupe_tool_configs(configs: list[WorkspaceToolConfig]) -> list[WorkspaceToolConfig]:
    seen: set[tuple[str, str, str]] = set()
    result: list[WorkspaceToolConfig] = []
    for config in configs:
        key = (config.name.lower(), config.source, config.tool_schema)
        if key in seen:
            continue
        seen.add(key)
        result.append(config)
    return result


def _unique_tool_import_path(name: str) -> Path:
    ensure_runtime_dirs()
    base = CONFIG_TOOLS_DIR / (name or f"tools_{uuid4().hex[:8]}")
    candidate = base
    index = 2
    while candidate.exists():
        candidate = CONFIG_TOOLS_DIR / f"{base.name}_{index}"
        index += 1
    return candidate


def _safe_uploaded_relative_path(filename: str | None) -> PurePosixPath | None:
    text = str(filename or "").replace("\\", "/").strip("/")
    if not text:
        return None
    path = PurePosixPath(text)
    safe_parts = [part for part in path.parts if part not in {"", ".", ".."}]
    if not safe_parts:
        return None
    return PurePosixPath(*safe_parts)


def _strip_uploaded_root(path: PurePosixPath, root_name: str) -> PurePosixPath:
    root = str(root_name or "").replace("\\", "/").strip("/").split("/", 1)[0]
    if root and len(path.parts) > 1 and path.parts[0] == root:
        return PurePosixPath(*path.parts[1:])
    return path


def _read_skill_configs() -> list[WorkspaceSkillConfig]:
    ensure_runtime_dirs()
    if not WORKSPACE_SKILLS_FILE.exists():
        return []
    try:
        raw = json.loads(WORKSPACE_SKILLS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(raw, list):
        return []
    return _normalize_skill_configs([WorkspaceSkillConfig.model_validate(item) for item in raw if isinstance(item, dict)])


def _write_skill_configs(configs: list[WorkspaceSkillConfig]) -> None:
    _write_workspace_list(WORKSPACE_SKILLS_FILE, [config.model_dump(by_alias=True) for config in configs])


def _copy_local_skill_source(source: str, warnings: list[str]) -> Path:
    ensure_runtime_dirs()
    source_path = Path(source).expanduser().resolve()
    if not source_path.exists():
        raise HTTPException(status_code=400, detail=f"本地路径不存在：{source}")

    destination = _unique_skill_import_path(_slugify(source_path.stem if source_path.is_file() else source_path.name))
    if source_path.is_file():
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination / source_path.name)
    else:
        if _is_relative_to(source_path, CONFIG_SKILLS_DIR.resolve()):
            warnings.append("导入源已位于 config/skills 下，直接复用该目录。")
            return source_path
        shutil.copytree(source_path, destination, ignore=_ignore_import_files)
    return destination


def _clone_skill_repository(source: str, use_mirror: bool, warnings: list[str]) -> Path:
    ensure_runtime_dirs()
    repo_slug = _github_repo_slug(source)
    if not repo_slug:
        raise HTTPException(status_code=400, detail="请提供有效的 GitHub 仓库地址，例如 https://github.com/org/repo。")
    destination = _unique_skill_import_path(repo_slug.replace("/", "__"))
    urls = _github_clone_candidates(source, use_mirror)
    errors: list[str] = []
    for url in urls:
        try:
            subprocess.run(
                ["git", "clone", "--depth", "1", url, str(destination)],
                check=True,
                capture_output=True,
                text=True,
                timeout=180,
            )
            if url != source:
                warnings.append(f"已通过 GitHub 镜像源 clone：{url}")
            return destination
        except (subprocess.SubprocessError, OSError) as error:
            if destination.exists():
                shutil.rmtree(destination, ignore_errors=True)
            errors.append(str(error))
    raise HTTPException(status_code=502, detail=f"GitHub 仓库 clone 失败：{'; '.join(errors[-2:])}")


def _detect_skill_configs(root: Path, source_type: str) -> tuple[list[WorkspaceSkillConfig], list[str], list[str]]:
    warnings: list[str] = []
    markdown_files = _candidate_skill_markdown_files(root)
    detected_files: list[str] = []
    configs: list[WorkspaceSkillConfig] = []
    source_root = root.parent if root.is_file() else root

    skill_files = sorted((path for path in markdown_files if path.name.lower() == "skill.md"), key=lambda path: path.as_posix().lower())
    skill_dirs = [path.parent.resolve() for path in skill_files]

    for path in skill_files:
        related = _related_skill_markdown_files(path.parent, path, skill_dirs)
        detected_files.append(str(path))
        detected_files.extend(str(item) for item in related)
        configs.append(_skill_config_from_markdown(path, path.parent, source_root, source_type, "codex_skill", related))

    for path in markdown_files:
        if path.name.lower() == "skill.md":
            continue
        if _is_under_any_directory(path, skill_dirs):
            continue
        detected_files.append(str(path))
        configs.append(_skill_config_from_markdown(path, path.parent, source_root, source_type, "markdown", []))

    if not configs and markdown_files:
        warnings.append("检测到了 Markdown 文件，但未能生成有效 Skill 配置。")
    return _normalize_skill_configs(_dedupe_skill_configs(configs)), _dedupe_strings(detected_files), warnings


def _candidate_skill_markdown_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root] if root.suffix.lower() in {".md", ".markdown"} and not _should_skip_import_path(root) else []

    result: list[Path] = []
    try:
        for path in root.rglob("*"):
            if len(result) >= 800:
                break
            if not path.is_file() or _should_skip_import_path(path):
                continue
            if path.suffix.lower() in {".md", ".markdown"}:
                result.append(path)
    except OSError:
        pass
    return sorted(result, key=lambda path: path.as_posix().lower())


def _related_skill_markdown_files(skill_root: Path, skill_file: Path, skill_dirs: list[Path]) -> list[Path]:
    result: list[Path] = []
    try:
        for path in skill_root.rglob("*"):
            if len(result) >= 120:
                break
            if not path.is_file() or path == skill_file or _should_skip_import_path(path):
                continue
            if path.suffix.lower() not in {".md", ".markdown"} or path.name.lower() == "skill.md":
                continue
            if _is_under_any_directory(path, [directory for directory in skill_dirs if directory != skill_root.resolve()]):
                continue
            result.append(path)
    except OSError:
        pass
    return sorted(result, key=lambda path: path.as_posix().lower())


def _skill_config_from_markdown(
    path: Path,
    skill_root: Path,
    source_root: Path,
    source_type: str,
    kind: str,
    related_files: list[Path],
) -> WorkspaceSkillConfig:
    content = _read_text_file(path)
    frontmatter, body = _parse_markdown_frontmatter(content)
    relative_path = _relative_import_path(path, source_root)
    related_relative_paths = [_relative_import_path(item, source_root) for item in related_files]
    name = _first_non_empty(
        frontmatter.get("name"),
        frontmatter.get("title"),
        _first_markdown_heading(body),
        _humanize_skill_name(skill_root.name if kind == "codex_skill" else path.stem),
    )
    description = _first_non_empty(
        frontmatter.get("description"),
        frontmatter.get("summary"),
        _markdown_description(body),
        f"从 {relative_path} 导入的 Skill",
    )
    metadata = {
        "kind": kind,
        "relativePath": relative_path,
        "skillRoot": _relative_import_path(skill_root, source_root),
        "relatedFiles": related_relative_paths,
    }
    return WorkspaceSkillConfig(
        id=f"skill_{_slugify(name)}_{uuid4().hex[:6]}",
        name=name,
        description=description,
        sourceType=source_type,
        sourcePath=str(source_root),
        filePath=str(path),
        content=content,
        metadataJson=_json_dumps(metadata),
        enabled=True,
    )


def _parse_markdown_frontmatter(content: str) -> tuple[dict[str, str], str]:
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, content
    end_index = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_index = index
            break
    if end_index is None:
        return {}, content
    metadata: dict[str, str] = {}
    for line in lines[1:end_index]:
        match = re.match(r"^([A-Za-z0-9_-]+)\s*:\s*(.*)$", line.strip())
        if not match:
            continue
        key = match.group(1).strip()
        value = match.group(2).strip().strip('"').strip("'")
        metadata[key] = value
    return metadata, "\n".join(lines[end_index + 1 :]).lstrip()


def _first_markdown_heading(content: str) -> str:
    for line in content.splitlines():
        match = re.match(r"^#\s+(.+)$", line.strip())
        if match:
            return match.group(1).strip()
    return ""


def _markdown_description(content: str) -> str:
    for line in content.splitlines():
        text = line.strip()
        if not text or text.startswith("#") or text.startswith("```") or text == "---":
            continue
        return text[:240]
    return ""


def _humanize_skill_name(value: str) -> str:
    text = value.strip().replace("_", " ").replace("-", " ")
    return " ".join(part for part in text.split() if part).title() or "未命名 Skill"


def _read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _merge_skill_configs(existing: list[WorkspaceSkillConfig], imported: list[WorkspaceSkillConfig]) -> list[WorkspaceSkillConfig]:
    merged = [*existing]
    for item in imported:
        base_name = item.name
        candidate = item
        suffix = 2
        existing_names = {config.name.lower() for config in merged}
        while candidate.name.lower() in existing_names:
            candidate = candidate.model_copy(update={"name": f"{base_name} {suffix}", "id": f"{item.id}_{suffix}"})
            suffix += 1
        merged.append(candidate)
    return _normalize_skill_configs(merged)


def _dedupe_skill_configs(configs: list[WorkspaceSkillConfig]) -> list[WorkspaceSkillConfig]:
    seen: set[tuple[str, str, str]] = set()
    result: list[WorkspaceSkillConfig] = []
    for config in configs:
        key = (config.name.lower(), config.file_path, config.content)
        if key in seen:
            continue
        seen.add(key)
        result.append(config)
    return result


def _unique_skill_import_path(name: str) -> Path:
    ensure_runtime_dirs()
    base = CONFIG_SKILLS_DIR / (name or f"skills_{uuid4().hex[:8]}")
    candidate = base
    index = 2
    while candidate.exists():
        candidate = CONFIG_SKILLS_DIR / f"{base.name}_{index}"
        index += 1
    return candidate


def _is_under_any_directory(path: Path, directories: list[Path]) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path
    return any(_is_relative_to(resolved, directory) for directory in directories)


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


def _copy_local_mcp_source(source: str, warnings: list[str]) -> Path:
    ensure_runtime_dirs()
    source_path = Path(source).expanduser().resolve()
    if not source_path.exists():
        raise HTTPException(status_code=400, detail=f"本地路径不存在：{source}")

    destination = _unique_import_path(_slugify(source_path.stem if source_path.is_file() else source_path.name))
    if source_path.is_file():
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination / source_path.name)
    else:
        if _is_relative_to(source_path, CONFIG_MCP_DIR.resolve()):
            warnings.append("导入源已位于 config/mcp 下，直接复用该目录。")
            return source_path
        shutil.copytree(source_path, destination, ignore=_ignore_import_files)
    return destination


def _clone_mcp_repository(source: str, use_mirror: bool, warnings: list[str]) -> Path:
    ensure_runtime_dirs()
    repo_slug = _github_repo_slug(source)
    if not repo_slug:
        raise HTTPException(status_code=400, detail="请提供有效的 GitHub 仓库地址，例如 https://github.com/org/repo。")
    destination = _unique_import_path(repo_slug.replace("/", "__"))
    urls = _github_clone_candidates(source, use_mirror)
    errors: list[str] = []
    for url in urls:
        try:
            subprocess.run(
                ["git", "clone", "--depth", "1", url, str(destination)],
                check=True,
                capture_output=True,
                text=True,
                timeout=180,
            )
            if url != source:
                warnings.append(f"已通过 GitHub 镜像源 clone：{url}")
            return destination
        except (subprocess.SubprocessError, OSError) as error:
            if destination.exists():
                shutil.rmtree(destination, ignore_errors=True)
            errors.append(str(error))
    raise HTTPException(status_code=502, detail=f"GitHub 仓库 clone 失败：{'; '.join(errors[-2:])}")


def _detect_mcp_server_configs(root: Path, source_type: str) -> tuple[list[WorkspaceMcpServerConfig], list[str], list[str]]:
    detected_files: list[str] = []
    warnings: list[str] = []
    configs: list[WorkspaceMcpServerConfig] = []

    for path in _candidate_mcp_config_files(root):
        detected_files.append(str(path))
        if path.suffix.lower() == ".toml":
            configs.extend(_read_mcp_configs_from_toml(path, root, source_type, warnings))
        elif path.suffix.lower() == ".json":
            configs.extend(_read_mcp_configs_from_json(path, root, source_type, warnings))

    if not configs:
        inferred = _infer_mcp_config_from_package(root, source_type)
        if inferred:
            configs.append(inferred)
            detected_files.append(str(root / "package.json"))
            warnings.append("未发现显式 MCP 配置，已根据 package.json 推断一个本地 STDIO MCP。")

    return _normalize_mcp_server_configs(_dedupe_mcp_configs(configs)), _dedupe_strings(detected_files), warnings


def _candidate_mcp_config_files(root: Path) -> list[Path]:
    candidates = [
        root / ".codex" / "config.toml",
        root / "config.toml",
        root / "mcp.json",
        root / ".mcp.json",
        root / "mcp-config.json",
        root / ".cursor" / "mcp.json",
        root / ".vscode" / "mcp.json",
    ]
    result: list[Path] = [path for path in candidates if path.is_file()]
    try:
        for path in root.rglob("config.toml"):
            if len(result) >= 20:
                break
            if _should_skip_import_path(path):
                continue
            if path not in result:
                text = path.read_text(encoding="utf-8", errors="ignore")
                if "mcp_servers" in text:
                    result.append(path)
        for path in root.rglob("*mcp*.json"):
            if len(result) >= 40:
                break
            if _should_skip_import_path(path) or path in result:
                continue
            result.append(path)
    except OSError:
        pass
    return result


def _read_mcp_configs_from_toml(path: Path, root: Path, source_type: str, warnings: list[str]) -> list[WorkspaceMcpServerConfig]:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        warnings.append(f"TOML 解析失败：{path}：{error}")
        return []
    servers = data.get("mcp_servers")
    if not isinstance(servers, dict):
        return []
    configs: list[WorkspaceMcpServerConfig] = []
    for server_key, raw in servers.items():
        if isinstance(raw, dict):
            config = _mcp_config_from_codex_table(str(server_key), raw, root, source_type)
            if config:
                configs.append(config)
    return configs


def _read_mcp_configs_from_json(path: Path, root: Path, source_type: str, warnings: list[str]) -> list[WorkspaceMcpServerConfig]:
    data = _read_json_object(path)
    if not data:
        return []
    raw_servers = data.get("mcpServers") or data.get("mcp_servers") or data.get("servers")
    if not isinstance(raw_servers, dict):
        return []
    configs: list[WorkspaceMcpServerConfig] = []
    for server_key, raw in raw_servers.items():
        if isinstance(raw, dict):
            config = _mcp_config_from_json_object(str(server_key), raw, root, source_type)
            if config:
                configs.append(config)
    return configs


def _mcp_config_from_codex_table(server_key: str, raw: dict[str, Any], root: Path, source_type: str) -> WorkspaceMcpServerConfig | None:
    command = _first_non_empty(raw.get("command"))
    url = _first_non_empty(raw.get("url"))
    if not command and not url:
        return None
    transport = "http" if url else "stdio"
    cwd = _resolve_import_cwd(root, _first_non_empty(raw.get("cwd")))
    args = raw.get("args") if isinstance(raw.get("args"), list) else []
    env = raw.get("env") if isinstance(raw.get("env"), dict) else {}
    env_vars = raw.get("env_vars") if isinstance(raw.get("env_vars"), list) else []
    http_headers = raw.get("http_headers") if isinstance(raw.get("http_headers"), dict) else {}
    env_http_headers = raw.get("env_http_headers") if isinstance(raw.get("env_http_headers"), dict) else {}
    return WorkspaceMcpServerConfig(
        id=f"mcp_{_slugify(server_key)}_{uuid4().hex[:6]}",
        name=_humanize_mcp_name(server_key),
        transport=transport,
        command=command,
        argsJson=_json_dumps(args),
        envJson=_json_dumps(_redact_secret_mapping(env)),
        envVarsJson=_json_dumps(env_vars),
        cwd=cwd,
        url=url,
        bearerTokenEnvVar=_safe_env_name(_first_non_empty(raw.get("bearer_token_env_var"))),
        httpHeadersJson=_json_dumps(_redact_secret_mapping(http_headers)),
        envHttpHeadersJson=_json_dumps(env_http_headers),
        enabled=raw.get("enabled") is not False,
        startupTimeoutSec=_positive_int(raw.get("startup_timeout_sec"), 10),
        toolTimeoutSec=_positive_int(raw.get("tool_timeout_sec"), 60),
        enabledToolsJson=_json_dumps(raw.get("enabled_tools") if isinstance(raw.get("enabled_tools"), list) else []),
        disabledToolsJson=_json_dumps(raw.get("disabled_tools") if isinstance(raw.get("disabled_tools"), list) else []),
        defaultToolsApprovalMode=_first_non_empty(raw.get("default_tools_approval_mode")),
        sourceType=source_type,
        sourcePath=str(root),
        description="从 Codex config.toml 导入",
    )


def _mcp_config_from_json_object(server_key: str, raw: dict[str, Any], root: Path, source_type: str) -> WorkspaceMcpServerConfig | None:
    command = _first_non_empty(raw.get("command"))
    url = _first_non_empty(raw.get("url"), raw.get("serverUrl"), raw.get("endpoint"))
    if not command and not url:
        return None
    transport = "http" if url else "stdio"
    args = raw.get("args") if isinstance(raw.get("args"), list) else []
    env = raw.get("env") if isinstance(raw.get("env"), dict) else {}
    headers = raw.get("headers") if isinstance(raw.get("headers"), dict) else {}
    env_headers = raw.get("envHttpHeaders") if isinstance(raw.get("envHttpHeaders"), dict) else raw.get("env_http_headers")
    env_headers = env_headers if isinstance(env_headers, dict) else {}
    return WorkspaceMcpServerConfig(
        id=f"mcp_{_slugify(server_key)}_{uuid4().hex[:6]}",
        name=_humanize_mcp_name(_first_non_empty(raw.get("name"), server_key)),
        transport=transport,
        command=command,
        argsJson=_json_dumps(args),
        envJson=_json_dumps(_redact_secret_mapping(env)),
        envVarsJson=_json_dumps(raw.get("env_vars") if isinstance(raw.get("env_vars"), list) else []),
        cwd=_resolve_import_cwd(root, _first_non_empty(raw.get("cwd"))),
        url=url,
        bearerTokenEnvVar=_safe_env_name(_first_non_empty(raw.get("bearerTokenEnvVar"), raw.get("bearer_token_env_var"))),
        httpHeadersJson=_json_dumps(_redact_secret_mapping(headers)),
        envHttpHeadersJson=_json_dumps(env_headers),
        enabled=raw.get("disabled") is not True and raw.get("enabled") is not False,
        sourceType=source_type,
        sourcePath=str(root),
        description=_first_non_empty(raw.get("description"), "从 MCP JSON 配置导入"),
    )


def _infer_mcp_config_from_package(root: Path, source_type: str) -> WorkspaceMcpServerConfig | None:
    package_path = root / "package.json"
    package_data = _read_json_object(package_path)
    if not package_data:
        return None
    package_name = _first_non_empty(package_data.get("name"), root.name)
    scripts = package_data.get("scripts") if isinstance(package_data.get("scripts"), dict) else {}
    if "start" in scripts:
        command = "npm"
        args = ["run", "start"]
        description = "根据 package.json scripts.start 推断"
    else:
        command = "npx"
        args = ["-y", package_name]
        description = "根据 package.json name 推断"
    return WorkspaceMcpServerConfig(
        id=f"mcp_{_slugify(package_name)}_{uuid4().hex[:6]}",
        name=_humanize_mcp_name(package_name),
        transport="stdio",
        command=command,
        argsJson=_json_dumps(args),
        cwd=str(root),
        sourceType=source_type,
        sourcePath=str(root),
        description=description,
    )


def _merge_mcp_server_configs(existing: list[WorkspaceMcpServerConfig], imported: list[WorkspaceMcpServerConfig]) -> list[WorkspaceMcpServerConfig]:
    merged = [*existing]
    for item in imported:
        base_name = item.name
        candidate = item
        suffix = 2
        existing_names = {config.name.lower() for config in merged}
        while candidate.name.lower() in existing_names:
            candidate = candidate.model_copy(update={"name": f"{base_name} {suffix}", "id": f"{item.id}_{suffix}"})
            suffix += 1
        merged.append(candidate)
    return _normalize_mcp_server_configs(merged)


def _dedupe_mcp_configs(configs: list[WorkspaceMcpServerConfig]) -> list[WorkspaceMcpServerConfig]:
    seen: set[tuple[str, str, str]] = set()
    result: list[WorkspaceMcpServerConfig] = []
    for config in configs:
        key = (config.transport, config.command or config.url, config.args_json)
        if key in seen:
            continue
        seen.add(key)
        result.append(config)
    return result


def _unique_import_path(name: str) -> Path:
    ensure_runtime_dirs()
    base = CONFIG_MCP_DIR / (name or f"mcp_{uuid4().hex[:8]}")
    candidate = base
    index = 2
    while candidate.exists():
        candidate = CONFIG_MCP_DIR / f"{base.name}_{index}"
        index += 1
    return candidate


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


def _normalize_skill_configs(configs: list[WorkspaceSkillConfig]) -> list[WorkspaceSkillConfig]:
    normalized: list[WorkspaceSkillConfig] = []
    for config in configs:
        normalized.append(
            config.model_copy(
                update={
                    "id": config.id.strip() or f"skill_{uuid4().hex[:8]}",
                    "name": config.name.strip() or "未命名 Skill",
                    "description": config.description.strip(),
                    "source_type": config.source_type.strip() or "manual",
                    "source_path": config.source_path.strip(),
                    "file_path": config.file_path.strip(),
                    "metadata_json": _ensure_json_text(config.metadata_json, {}),
                    "enabled": config.enabled is not False,
                },
            ),
        )
    return normalized


def _normalize_mcp_server_configs(configs: list[WorkspaceMcpServerConfig]) -> list[WorkspaceMcpServerConfig]:
    normalized: list[WorkspaceMcpServerConfig] = []
    for config in configs:
        transport = config.transport.strip().lower() or "stdio"
        if transport in {"streamable_http", "sse"}:
            transport = "http"
        default_approval = config.default_tools_approval_mode.strip()
        if default_approval not in {"", "auto", "prompt", "approve"}:
            default_approval = ""
        normalized.append(
            config.model_copy(
                update={
                    "id": config.id.strip() or f"mcp_{uuid4().hex[:8]}",
                    "name": config.name.strip() or "未命名 MCP",
                    "transport": transport,
                    "command": config.command.strip(),
                    "args_json": _ensure_json_text(config.args_json, []),
                    "env_json": _ensure_json_text(config.env_json, {}),
                    "env_vars_json": _ensure_json_text(config.env_vars_json, []),
                    "cwd": config.cwd.strip(),
                    "url": config.url.strip(),
                    "bearer_token_env_var": _safe_env_name(config.bearer_token_env_var),
                    "http_headers_json": _ensure_json_text(config.http_headers_json, {}),
                    "env_http_headers_json": _ensure_json_text(config.env_http_headers_json, {}),
                    "enabled": config.enabled is not False,
                    "startup_timeout_sec": max(1, int(config.startup_timeout_sec or 10)),
                    "tool_timeout_sec": max(1, int(config.tool_timeout_sec or 60)),
                    "enabled_tools_json": _ensure_json_text(config.enabled_tools_json, []),
                    "disabled_tools_json": _ensure_json_text(config.disabled_tools_json, []),
                    "default_tools_approval_mode": default_approval,
                    "source_type": config.source_type.strip() or "manual",
                    "source_path": config.source_path.strip(),
                    "description": config.description.strip(),
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
        api_key_mode = "direct" if config.api_key_mode.strip() == "direct" else "env"
        normalized.append(
            config.model_copy(
                update={
                    "id": config.id.strip() or f"model_{uuid4().hex[:8]}",
                    "name": config.name.strip() or "未命名模型配置",
                    "provider": config.provider.strip() or "openai",
                    "model": config.model.strip(),
                    "api_key": config.api_key.strip() if api_key_mode == "direct" else "",
                    "api_key_env": _safe_env_name(config.api_key_env) if api_key_mode == "env" else "",
                    "api_key_mode": api_key_mode,
                    "is_default": is_default,
                },
            ),
        )
    return normalized


def _safe_env_name(value: str) -> str:
    text = value.strip()
    return text if _is_env_name(text) else ""


def _is_env_name(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value or ""))


def _slugify(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip().strip("/\\"))
    text = text.strip("._-")
    return text[:80] or f"mcp_{uuid4().hex[:8]}"


def _humanize_mcp_name(value: str) -> str:
    text = value.strip().replace("@", "").replace("/", " ").replace("_", " ").replace("-", " ")
    return " ".join(part for part in text.split() if part).title() or "未命名 MCP"


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def _ensure_json_text(value: str, fallback: Any) -> str:
    try:
        parsed = json.loads(value or "")
    except (TypeError, json.JSONDecodeError):
        return _json_dumps(fallback)
    return _json_dumps(parsed)


def _redact_secret_mapping(value: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, raw_value in value.items():
        key_text = str(key)
        if _looks_secret_key(key_text) and str(raw_value or "").strip():
            result[key_text] = ""
        else:
            result[key_text] = raw_value
    return result


def _looks_secret_key(value: str) -> bool:
    return bool(re.search(r"(key|secret|token|password|authorization|bearer)", value, re.IGNORECASE))


def _resolve_import_cwd(root: Path, cwd: str) -> str:
    if not cwd:
        return ""
    path = Path(cwd).expanduser()
    if path.is_absolute():
        return str(path)
    return str((root / path).resolve())


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _ignore_import_files(directory: str, names: list[str]) -> set[str]:
    ignored = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next", ".cache"}
    return {name for name in names if name in ignored}


def _should_skip_import_path(path: Path) -> bool:
    return any(part in {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next", ".cache"} for part in path.parts)


def _github_repo_slug(source: str) -> str:
    text = source.strip().removesuffix(".git")
    match = re.search(r"github\.com[:/](?P<owner>[^/\s]+)/(?P<repo>[^/\s?#]+)", text)
    if not match:
        match = re.fullmatch(r"(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+)", text)
    if not match:
        return ""
    return f"{match.group('owner')}/{match.group('repo').removesuffix('.git')}"


def _github_clone_candidates(source: str, use_mirror: bool) -> list[str]:
    slug = _github_repo_slug(source)
    original = source.strip()
    if slug and not re.match(r"^(https?|git@)", original):
        original = f"https://github.com/{slug}.git"
    candidates: list[str] = []
    if use_mirror:
        candidates.extend([
            f"https://gh.llkk.cc/https://github.com/{slug}.git",
            f"https://ghproxy.net/https://github.com/{slug}.git",
            f"https://gh-proxy.com/https://github.com/{slug}.git",
        ])
    candidates.append(original)
    return _dedupe_strings(candidates)


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
