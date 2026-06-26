from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from app.compiler import SmokeTestFailedError, SmokeTestResult, build_project, export_project_zip
from app.config import EXPORTS_DIR, STORAGE_DIR, ensure_runtime_dirs
from app.ir.sanitization import sanitized_project
from app.ir.schemas import ProjectIR, create_default_project
from app.ir.validation import validate_project
from app.project_store import project_path, read_project, write_project
from app.run_store import clear_run_records, delete_run_record, list_run_records, save_run_record
from app.runtime_environment import RuntimeEnvironmentConfig, resolve_runtime_environment
from app.runner import (
    collect_data_shaping_paths,
    iter_project_preview_events,
    preview_data_shaping_node,
    run_project_preview as run_project_preview_engine,
)


router = APIRouter(prefix="/api", tags=["projects"])


class CreateProjectRequest(BaseModel):
    name: str = "Untitled Agent"
    kind: str = "agent"


class CompileResponse(BaseModel):
    buildPath: str
    files: list[str]


class SmokeTestResponse(BaseModel):
    passed: bool
    command: list[str]
    exitCode: int
    durationMs: float
    stdout: str = ""
    stderr: str = ""


class ExportResponse(BaseModel):
    exportId: str
    downloadUrl: str
    files: list[str]
    smokeTest: SmokeTestResponse


class RunModelConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    id: str = ""
    name: str = ""
    provider: str = "openai"
    model: str = ""
    base_url: str = Field("", alias="baseUrl")
    api_key: str = Field("", alias="apiKey")
    api_key_env: str = Field("", alias="apiKeyEnv")
    api_version: str = Field("", alias="apiVersion")
    organization: str = ""
    enabled: bool = True
    is_default: bool = Field(False, alias="isDefault")
    notes: str = ""


class RunPreviewRequest(BaseModel):
    input: dict[str, Any] = Field(default_factory=dict)
    mode: Literal["dry", "live"] = "dry"
    modelConfig: RunModelConfig | None = None
    runtimeEnvironment: RuntimeEnvironmentConfig | None = None


class DataShapingPathsRequest(BaseModel):
    runId: str = ""
    state: dict[str, Any] = Field(default_factory=dict)


class DataShapingPreviewRequest(BaseModel):
    nodeId: str
    runId: str = ""
    state: dict[str, Any] = Field(default_factory=dict)
    modelConfig: RunModelConfig | None = None


class RunTraceItem(BaseModel):
    nodeId: str
    type: str
    label: str
    status: str = "ok"
    detail: str = ""
    durationMs: float = 0
    inputState: dict[str, Any] = Field(default_factory=dict)
    outputDelta: dict[str, Any] = Field(default_factory=dict)
    virtual: bool = False
    parentNodeId: str | None = None
    position: dict[str, float] | None = None


class RunPreviewResponse(BaseModel):
    mode: Literal["dry", "live"]
    valid: bool
    issues: list[dict[str, Any]]
    trace: list[RunTraceItem]
    outputState: dict[str, Any]


class RunHistoryRecordPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    projectId: str = ""


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
    write_project(project)
    return project


@router.get("/projects/{project_id}", response_model=ProjectIR)
def get_project(project_id: str) -> ProjectIR:
    return read_project(project_id)


@router.put("/projects/{project_id}", response_model=ProjectIR)
def save_project(project_id: str, project: ProjectIR) -> ProjectIR:
    if project.project.id != project_id:
        project.project.id = project_id
    project = sanitized_project(project)
    write_project(project)
    return project


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: str) -> None:
    path = project_path(project_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Project not found")
    path.unlink()
    clear_run_records(project_id)


@router.post("/projects/{project_id}/validate")
def validate_saved_project(project_id: str):
    project = read_project(project_id)
    return validate_project(project)


@router.post("/projects/{project_id}/compile", response_model=CompileResponse)
def compile_saved_project(project_id: str) -> CompileResponse:
    project = read_project(project_id)
    result = validate_project(project)
    if not result.valid:
        raise HTTPException(status_code=422, detail=[issue.model_dump() for issue in result.issues])
    build_dir, files = build_project(project)
    return CompileResponse(buildPath=str(build_dir), files=files)


@router.post("/projects/{project_id}/run", response_model=RunPreviewResponse)
def run_project_preview(project_id: str, payload: RunPreviewRequest | None = None) -> RunPreviewResponse:
    project = read_project(project_id)
    request = payload or RunPreviewRequest()
    runtime_environment = resolve_runtime_environment(request.runtimeEnvironment, project.project.runtime_environment_id)
    result = validate_project(project)
    if request.mode == "live" and not result.valid:
        trace: list[dict[str, Any]] = []
        output_state = dict(request.input)
    else:
        trace, output_state = run_project_preview_engine(
            project,
            request.input,
            request.mode,
            request.modelConfig.model_dump(by_alias=True) if request.modelConfig else None,
            runtime_environment,
        )
    return RunPreviewResponse(
        mode=request.mode,
        valid=result.valid,
        issues=[issue.model_dump() for issue in result.issues],
        trace=trace,
        outputState=output_state,
    )


@router.post("/projects/{project_id}/data-shaping/paths")
def list_project_data_shaping_paths(project_id: str, payload: DataShapingPathsRequest | None = None) -> dict[str, Any]:
    project = read_project(project_id)
    request = payload or DataShapingPathsRequest()
    run_record = _find_run_record(project_id, request.runId)
    return {
        "paths": collect_data_shaping_paths(project, request.state, run_record),
    }


@router.post("/projects/{project_id}/data-shaping/preview")
def preview_project_data_shaping(project_id: str, payload: DataShapingPreviewRequest) -> dict[str, Any]:
    project = read_project(project_id)
    run_record = _find_run_record(project_id, payload.runId)
    state = payload.state or _output_state_from_run_record(run_record)
    result = preview_data_shaping_node(
        project,
        payload.nodeId,
        state,
        payload.modelConfig.model_dump(by_alias=True) if payload.modelConfig else None,
    )
    result["paths"] = collect_data_shaping_paths(project, state, run_record)
    return result


@router.get("/projects/{project_id}/runs")
def list_project_runs(project_id: str) -> list[dict[str, Any]]:
    read_project(project_id)
    return list_run_records(project_id)


@router.post("/projects/{project_id}/runs")
def save_project_run(project_id: str, record: RunHistoryRecordPayload) -> dict[str, Any]:
    read_project(project_id)
    return save_run_record(project_id, record.model_dump(mode="json"))


@router.delete("/projects/{project_id}/runs/{run_id}", status_code=204)
def delete_project_run(project_id: str, run_id: str) -> None:
    read_project(project_id)
    delete_run_record(project_id, run_id)


@router.delete("/projects/{project_id}/runs", status_code=204)
def clear_project_runs(project_id: str) -> None:
    read_project(project_id)
    clear_run_records(project_id)


def _find_run_record(project_id: str, run_id: str) -> dict[str, Any] | None:
    if not run_id:
        return None
    for record in list_run_records(project_id):
        if str(record.get("id") or "") == run_id:
            return record
    return None


def _output_state_from_run_record(record: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(record, dict):
        return {}
    result = record.get("result") if isinstance(record.get("result"), dict) else {}
    output_state = result.get("outputState") if isinstance(result.get("outputState"), dict) else {}
    return dict(output_state)


@router.post("/projects/{project_id}/run/stream")
def stream_project_preview(project_id: str, payload: RunPreviewRequest | None = None) -> StreamingResponse:
    project = read_project(project_id)
    request = payload or RunPreviewRequest(mode="live")
    runtime_environment = resolve_runtime_environment(request.runtimeEnvironment, project.project.runtime_environment_id)

    def events():
        result = validate_project(project)
        issues = [issue.model_dump() for issue in result.issues]
        yield _json_line(
            {
                "event": "run_start",
                "mode": request.mode,
                "valid": result.valid,
                "issues": issues,
                "inputState": request.input,
            }
        )
        if request.mode == "live" and not result.valid:
            yield _json_line(
                {
                    "event": "run_end",
                    "mode": request.mode,
                    "valid": result.valid,
                    "issues": issues,
                    "trace": [],
                    "outputState": dict(request.input),
                }
            )
            return
        for event in iter_project_preview_events(
            project,
            request.input,
            request.mode,
            request.modelConfig.model_dump(by_alias=True) if request.modelConfig else None,
            runtime_environment,
        ):
            event["mode"] = request.mode
            event["valid"] = result.valid
            event["issues"] = issues
            yield _json_line(event)

    return StreamingResponse(events(), media_type="application/x-ndjson")


@router.post("/projects/{project_id}/export", response_model=ExportResponse)
def export_saved_project(project_id: str) -> ExportResponse:
    project = read_project(project_id)
    result = validate_project(project)
    if not result.valid:
        raise HTTPException(status_code=422, detail=[issue.model_dump() for issue in result.issues])
    try:
        export_id, _zip_path, files, smoke_test = export_project_zip(project)
    except SmokeTestFailedError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "导出工程 smoke test 未通过。",
                "smokeTest": _smoke_response(exc.result).model_dump(),
            },
        ) from exc
    return ExportResponse(
        exportId=export_id,
        downloadUrl=f"/api/exports/{export_id}",
        files=files,
        smokeTest=_smoke_response(smoke_test),
    )


@router.get("/exports/{export_id}")
def download_export(export_id: str):
    zip_path = EXPORTS_DIR / f"{export_id}.zip"
    if not zip_path.exists():
        raise HTTPException(status_code=404, detail="Export not found")
    return FileResponse(zip_path, filename=zip_path.name, media_type="application/zip")


def _json_line(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False) + "\n"


def _smoke_response(result: SmokeTestResult) -> SmokeTestResponse:
    return SmokeTestResponse(
        passed=result.passed,
        command=result.command,
        exitCode=result.exitCode,
        durationMs=result.durationMs,
        stdout=result.stdout,
        stderr=result.stderr,
    )
