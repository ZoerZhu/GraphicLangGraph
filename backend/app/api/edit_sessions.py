from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.edit_sessions import (
    EditSessionError,
    apply_patch_set,
    discard_patch_set,
    get_patch_session,
    rollback_patch_set,
    run_whitelisted_command,
)
from app.runtime_environment import RuntimeEnvironmentConfig, resolve_runtime_environment


router = APIRouter(prefix="/api/edit-sessions", tags=["edit-sessions"])


class EditSessionActionRequest(BaseModel):
    runtimeEnvironment: RuntimeEnvironmentConfig | None = None


class CommandRunRequest(BaseModel):
    command: str | list[str]
    cwd: str = "."
    timeoutSeconds: int = 60
    runtimeEnvironment: RuntimeEnvironmentConfig | None = None


@router.get("/{patch_id}")
def read_edit_session(patch_id: str) -> dict[str, Any]:
    return _guard(lambda: get_patch_session(patch_id))


@router.post("/{patch_id}/apply")
def apply_edit_session(patch_id: str, payload: EditSessionActionRequest | None = None) -> dict[str, Any]:
    runtime = resolve_runtime_environment(payload.runtimeEnvironment if payload else None)
    return _guard(lambda: apply_patch_set(patch_id, runtime))


@router.post("/{patch_id}/discard")
def discard_edit_session(patch_id: str) -> dict[str, Any]:
    return _guard(lambda: discard_patch_set(patch_id))


@router.post("/rollback/{rollback_id}")
def rollback_edit_session(rollback_id: str) -> dict[str, Any]:
    return _guard(lambda: rollback_patch_set(rollback_id))


@router.post("/commands/run")
def run_edit_command(payload: CommandRunRequest) -> dict[str, Any]:
    runtime = resolve_runtime_environment(payload.runtimeEnvironment)
    args = {"command": payload.command, "cwd": payload.cwd, "timeoutSeconds": payload.timeoutSeconds}
    return _guard(lambda: run_whitelisted_command(args, runtime))


def _guard(factory):
    try:
        return factory()
    except EditSessionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
