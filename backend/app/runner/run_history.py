from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from app.config import RUNS_DIR, ensure_runtime_dirs


RUN_HISTORY_LIMIT = 50


def run_project_dir(project_id: str) -> Path:
    safe_id = _safe_name(project_id)
    if not safe_id:
        raise HTTPException(status_code=404, detail="Project not found")
    return RUNS_DIR / safe_id


def run_record_path(project_id: str, run_id: str) -> Path:
    safe_run_id = _safe_name(run_id)
    if not safe_run_id:
        raise HTTPException(status_code=404, detail="Run record not found")
    return run_project_dir(project_id) / f"{safe_run_id}.json"


def list_run_records(project_id: str) -> list[dict[str, Any]]:
    ensure_runtime_dirs()
    directory = run_project_dir(project_id)
    if not directory.exists():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            records.append(data)
    return records[:RUN_HISTORY_LIMIT]


def find_run_record(project_id: str, run_id: str) -> dict[str, Any] | None:
    if not run_id:
        return None
    for record in list_run_records(project_id):
        if str(record.get("id") or "") == run_id:
            return record
    return None


def output_state_from_run_record(record: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(record, dict):
        return {}
    result = record.get("result") if isinstance(record.get("result"), dict) else {}
    output_state = result.get("outputState") if isinstance(result.get("outputState"), dict) else {}
    return dict(output_state)


def save_run_record(project_id: str, record: dict[str, Any]) -> dict[str, Any]:
    ensure_runtime_dirs()
    if not isinstance(record, dict):
        raise HTTPException(status_code=422, detail="Run record must be an object")
    run_id = str(record.get("id") or "").strip()
    if not run_id:
        raise HTTPException(status_code=422, detail="Run record id is required")
    record_project_id = str(record.get("projectId") or "").strip()
    if record_project_id and record_project_id != project_id:
        raise HTTPException(status_code=422, detail="Run record projectId mismatch")
    record["projectId"] = project_id
    directory = run_project_dir(project_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = run_record_path(project_id, run_id)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    _prune_run_records(directory)
    return record


def delete_run_record(project_id: str, run_id: str) -> None:
    path = run_record_path(project_id, run_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Run record not found")
    path.unlink()


def clear_run_records(project_id: str) -> None:
    directory = run_project_dir(project_id)
    if directory.exists():
        shutil.rmtree(directory)


def _prune_run_records(directory: Path) -> None:
    files = sorted(directory.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    for path in files[RUN_HISTORY_LIMIT:]:
        try:
            path.unlink()
        except OSError:
            continue


def _safe_name(value: str) -> str:
    return "".join(ch for ch in str(value or "") if ch.isalnum() or ch in "-_")
