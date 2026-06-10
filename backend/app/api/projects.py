from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.compiler import build_project, export_project_zip
from app.config import EXPORTS_DIR, STORAGE_DIR, ensure_runtime_dirs
from app.ir.schemas import ProjectIR, create_default_project
from app.ir.validation import validate_project


router = APIRouter(prefix="/api", tags=["projects"])


class CreateProjectRequest(BaseModel):
    name: str = "Untitled Agent"
    kind: str = "agent"


class CompileResponse(BaseModel):
    buildPath: str
    files: list[str]


class ExportResponse(BaseModel):
    exportId: str
    downloadUrl: str
    files: list[str]


class RunPreviewRequest(BaseModel):
    input: dict[str, Any] = {}


class RunTraceItem(BaseModel):
    nodeId: str
    type: str
    label: str
    status: str = "ok"
    detail: str = ""


class RunPreviewResponse(BaseModel):
    valid: bool
    issues: list[dict[str, Any]]
    trace: list[RunTraceItem]
    outputState: dict[str, Any]


class ProjectListItem(BaseModel):
    id: str
    name: str
    description: str = ""
    kind: str = "agent"
    nodeCount: int
    edgeCount: int
    toolCount: int
    mcpCount: int
    importedAgentCount: int
    updatedAt: str


@router.get("/projects", response_model=list[ProjectListItem])
def list_projects() -> list[ProjectListItem]:
    ensure_runtime_dirs()
    items: list[ProjectListItem] = []
    for path in sorted(STORAGE_DIR.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            project = ProjectIR.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        updated_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
        items.append(
            ProjectListItem(
                id=project.project.id,
                name=project.project.name,
                description=project.project.description,
                kind=project.project.kind,
                nodeCount=len(project.nodes),
                edgeCount=len(project.edges),
                toolCount=len(project.tools),
                mcpCount=len(project.mcpServers),
                importedAgentCount=len(project.importedAgents),
                updatedAt=updated_at,
            )
        )
    return items


@router.post("/projects", response_model=ProjectIR)
def create_project(payload: CreateProjectRequest | None = None) -> ProjectIR:
    ensure_runtime_dirs()
    project = create_default_project(
        payload.name if payload else "Untitled Agent",
        payload.kind if payload else "agent",
    )
    _write_project(project)
    return project


@router.get("/projects/{project_id}", response_model=ProjectIR)
def get_project(project_id: str) -> ProjectIR:
    return _read_project(project_id)


@router.put("/projects/{project_id}", response_model=ProjectIR)
def save_project(project_id: str, project: ProjectIR) -> ProjectIR:
    if project.project.id != project_id:
        project.project.id = project_id
    _write_project(project)
    return project


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: str) -> None:
    path = _project_path(project_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Project not found")
    path.unlink()


@router.post("/projects/{project_id}/validate")
def validate_saved_project(project_id: str):
    project = _read_project(project_id)
    return validate_project(project)


@router.post("/projects/{project_id}/compile", response_model=CompileResponse)
def compile_saved_project(project_id: str) -> CompileResponse:
    project = _read_project(project_id)
    result = validate_project(project)
    if not result.valid:
        raise HTTPException(status_code=422, detail=[issue.model_dump() for issue in result.issues])
    build_dir, files = build_project(project)
    return CompileResponse(buildPath=str(build_dir), files=files)


@router.post("/projects/{project_id}/run", response_model=RunPreviewResponse)
def run_project_preview(project_id: str, payload: RunPreviewRequest | None = None) -> RunPreviewResponse:
    project = _read_project(project_id)
    result = validate_project(project)
    trace, output_state = _dry_run_project(project, (payload.input if payload else {}) or {})
    return RunPreviewResponse(
        valid=result.valid,
        issues=[issue.model_dump() for issue in result.issues],
        trace=trace,
        outputState=output_state,
    )


@router.post("/projects/{project_id}/export", response_model=ExportResponse)
def export_saved_project(project_id: str) -> ExportResponse:
    project = _read_project(project_id)
    result = validate_project(project)
    if not result.valid:
        raise HTTPException(status_code=422, detail=[issue.model_dump() for issue in result.issues])
    export_id, _zip_path, files = export_project_zip(project)
    return ExportResponse(exportId=export_id, downloadUrl=f"/api/exports/{export_id}", files=files)


@router.get("/exports/{export_id}")
def download_export(export_id: str):
    zip_path = EXPORTS_DIR / f"{export_id}.zip"
    if not zip_path.exists():
        raise HTTPException(status_code=404, detail="Export not found")
    return FileResponse(zip_path, filename=zip_path.name, media_type="application/zip")


def _project_path(project_id: str) -> Path:
    ensure_runtime_dirs()
    safe_id = "".join(ch for ch in project_id if ch.isalnum() or ch in "-_")
    if not safe_id:
        raise HTTPException(status_code=400, detail="Invalid project id")
    return STORAGE_DIR / f"{safe_id}.json"


def _read_project(project_id: str) -> ProjectIR:
    path = _project_path(project_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Project not found")
    return ProjectIR.model_validate_json(path.read_text(encoding="utf-8"))


def _write_project(project: ProjectIR) -> None:
    path = _project_path(project.project.id)
    path.write_text(project.model_dump_json(by_alias=True, indent=2), encoding="utf-8")


def _dry_run_project(project: ProjectIR, input_state: dict[str, Any]) -> tuple[list[RunTraceItem], dict[str, Any]]:
    nodes = {node.id: node for node in project.nodes}
    outgoing: dict[str, list] = {}
    for edge in project.edges:
        outgoing.setdefault(edge.source, []).append(edge)

    start = next((node for node in project.nodes if node.type == "start"), None)
    if not start:
        return [], dict(input_state)

    state = dict(input_state)
    trace: list[RunTraceItem] = []
    current = _first_target(outgoing.get(start.id, []))
    visited = 0
    while current and current in nodes and visited < 80:
        visited += 1
        node = nodes[current]
        detail = _simulate_node(node, state)
        trace.append(RunTraceItem(nodeId=node.id, type=str(node.type), label=node.label, detail=detail))
        if str(node.type) == "direct_reply":
            break
        edges = outgoing.get(node.id, [])
        if not edges:
            break
        conditional_edges = [edge for edge in edges if str(edge.kind) == "conditional"]
        if conditional_edges:
            handle = _choose_handle(node, state)
            current = _target_for_handle(conditional_edges, handle) or _first_target(conditional_edges)
        else:
            current = _first_target(edges)

    if visited >= 80:
        trace.append(RunTraceItem(nodeId="__runtime__", type="custom_function", label="运行预览", status="error", detail="路径超过 80 步，可能存在循环。"))
    return trace, state


def _simulate_node(node, state: dict[str, Any]) -> str:
    config = node.config
    node_type = str(node.type)
    if node_type == "llm":
        field = str(config.get("outputField", "final_answer"))
        state[field] = f"[dry-run] {node.label} 将调用模型 {config.get('model', 'gpt-4.1-mini')}"
        return f"模拟 LLM 输出到 state.{field}"
    if node_type == "agent":
        field = str(config.get("outputField", "agent_result"))
        state[field] = f"[dry-run] {node.label} 将作为 Agent 执行"
        return f"模拟 Agent 输出到 state.{field}"
    if node_type == "tool":
        field = str(config.get("outputField", "tool_result"))
        state[field] = {"tool": config.get("toolName", node.label), "status": "dry-run"}
        return f"模拟 Tool 输出到 state.{field}"
    if node_type == "retriever":
        field = str(config.get("outputField", "retrieved_context"))
        state[field] = f"[dry-run] 从 {config.get('path', './knowledge')} 检索 top_k={config.get('topK', 4)}"
        return f"模拟 Retriever 输出到 state.{field}"
    if node_type == "condition":
        return f"按 state.{config.get('field', 'intent')} 选择分支"
    if node_type == "ai_router":
        field = str(config.get("routeField", "route_key"))
        fallback = str(config.get("fallback", "other"))
        state[field] = _infer_router_key(config, state) or fallback
        reason_field = str(config.get("reasonField", "route_reason"))
        state[reason_field] = "dry-run router decision"
        return f"模拟 AI Router 选择 {state[field]}"
    if node_type == "human_approval":
        action_field = str(config.get("actionField", "approval_action"))
        state[action_field] = str(state.get(action_field) or config.get("defaultAction", "approved"))
        output_field = str(config.get("outputField", "approval_result"))
        state[output_field] = {"action": state[action_field], "status": "dry-run"}
        return f"模拟人工审批动作 {state[action_field]}"
    if node_type == "http":
        field = str(config.get("outputField", "http_response"))
        state[field] = {"url": config.get("url", ""), "status": "dry-run"}
        return f"模拟 HTTP 输出到 state.{field}"
    if node_type == "direct_reply":
        field = str(config.get("outputField", "final_answer"))
        state[field] = state.get(field) or "[dry-run] Direct Reply"
        return f"终止并返回 state.{field}"
    if node_type in {"skill_node", "mcp_node", "agent_ref", "custom_function"}:
        field = str(config.get("outputField", f"{node_type}_result"))
        state[field] = f"[dry-run] {node.label}"
        return f"模拟输出到 state.{field}"
    return "跳过未知节点"


def _choose_handle(node, state: dict[str, Any]) -> str:
    config = node.config
    node_type = str(node.type)
    if node_type == "condition":
        field = str(config.get("field", ""))
        current = state.get(field)
        expected = str(config.get("value", ""))
        current_text = "" if current is None else str(current)
        operator = str(config.get("operator", "equals"))
        matched = (
            current_text == expected
            if operator == "equals"
            else expected in current_text
            if operator == "contains"
            else current_text != expected
            if operator == "not_equals"
            else False
        )
        return str(config.get("trueBranch" if matched else "falseBranch", config.get("fallback", "fallback")))
    if node_type == "ai_router":
        return str(state.get(str(config.get("routeField", "route_key"))) or config.get("fallback", "other"))
    if node_type == "human_approval":
        return str(state.get(str(config.get("actionField", "approval_action"))) or config.get("fallback", "rejected"))
    return str(config.get("fallback", "fallback"))


def _infer_router_key(config: dict[str, Any], state: dict[str, Any]) -> str | None:
    text = json.dumps(state, ensure_ascii=False).lower()
    for line in str(config.get("scenarios", "")).splitlines():
        parts = (line.split(":", 2) + ["", ""])[:3]
        key = parts[0].strip()
        keywords = [item.strip().lower() for item in parts[2].split(",") if item.strip()]
        if key and keywords and any(keyword in text for keyword in keywords):
            return key
    return None


def _first_target(edges: list) -> str | None:
    return edges[0].target if edges else None


def _target_for_handle(edges: list, handle: str) -> str | None:
    for edge in edges:
        if edge.sourceHandle == handle:
            return edge.target
    return None
