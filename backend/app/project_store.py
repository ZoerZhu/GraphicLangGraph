from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException

from app.config import STORAGE_DIR, ensure_runtime_dirs
from app.ir.schemas import ProjectIR


def project_path(project_id: str) -> Path:
    safe_id = "".join(ch for ch in project_id if ch.isalnum() or ch in "-_")
    if not safe_id:
        raise HTTPException(status_code=404, detail="Project not found")
    return STORAGE_DIR / f"{safe_id}.json"


def read_project(project_id: str) -> ProjectIR:
    ensure_runtime_dirs()
    path = project_path(project_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Project not found")
    return ProjectIR.model_validate_json(path.read_text(encoding="utf-8"))


def write_project(project: ProjectIR) -> None:
    ensure_runtime_dirs()
    path = project_path(project.project.id)
    path.write_text(project.model_dump_json(by_alias=True, indent=2), encoding="utf-8")
