from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.compiler import build_project, export_project_zip
from app.config import EXPORTS_DIR, STORAGE_DIR, ensure_runtime_dirs
from app.ir.schemas import ProjectIR, create_default_project
from app.ir.validation import validate_project
from app.runner import run_project_preview as run_project_preview_engine


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
    input: dict[str, Any] = Field(default_factory=dict)
    mode: Literal["dry", "live"] = "dry"


class RunTraceItem(BaseModel):
    nodeId: str
    type: str
    label: str
    status: str = "ok"
    detail: str = ""
    durationMs: float = 0
    inputState: dict[str, Any] = Field(default_factory=dict)
    outputDelta: dict[str, Any] = Field(default_factory=dict)


class RunPreviewResponse(BaseModel):
    mode: Literal["dry", "live"]
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
    request = payload or RunPreviewRequest()
    result = validate_project(project)
    if request.mode == "live" and not result.valid:
        trace: list[dict[str, Any]] = []
        output_state = dict(request.input)
    else:
        trace, output_state = run_project_preview_engine(project, request.input, request.mode)
    return RunPreviewResponse(
        mode=request.mode,
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
