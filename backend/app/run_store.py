from __future__ import annotations

from pathlib import Path
from typing import Any

from app.runner import run_history as _run_history


RUN_HISTORY_LIMIT = _run_history.RUN_HISTORY_LIMIT
RUNS_DIR = _run_history.RUNS_DIR


def _sync_runtime_dir() -> None:
    _run_history.RUNS_DIR = RUNS_DIR


def run_project_dir(project_id: str) -> Path:
    _sync_runtime_dir()
    return _run_history.run_project_dir(project_id)


def run_record_path(project_id: str, run_id: str) -> Path:
    _sync_runtime_dir()
    return _run_history.run_record_path(project_id, run_id)


def list_run_records(project_id: str) -> list[dict[str, Any]]:
    _sync_runtime_dir()
    return _run_history.list_run_records(project_id)


def save_run_record(project_id: str, record: dict[str, Any]) -> dict[str, Any]:
    _sync_runtime_dir()
    return _run_history.save_run_record(project_id, record)


def delete_run_record(project_id: str, run_id: str) -> None:
    _sync_runtime_dir()
    return _run_history.delete_run_record(project_id, run_id)


def clear_run_records(project_id: str) -> None:
    _sync_runtime_dir()
    return _run_history.clear_run_records(project_id)
