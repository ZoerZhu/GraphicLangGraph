from __future__ import annotations

from typing import Any

from app.edit_sessions import EditSessionError, propose_patch as _propose_patch, replace_in_file as _replace_in_file, run_whitelisted_command as _run_whitelisted_command, write_file as _write_file


def propose_patch(args: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    try:
        return _propose_patch(args, runtime)
    except EditSessionError as exc:
        raise RuntimeError(str(exc)) from exc


def replace_in_file(args: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    try:
        return _replace_in_file(args, runtime)
    except EditSessionError as exc:
        raise RuntimeError(str(exc)) from exc


def write_file(args: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    try:
        return _write_file(args, runtime)
    except EditSessionError as exc:
        raise RuntimeError(str(exc)) from exc


def run_whitelisted_command(args: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    try:
        return _run_whitelisted_command(args, runtime)
    except EditSessionError as exc:
        raise RuntimeError(str(exc)) from exc
