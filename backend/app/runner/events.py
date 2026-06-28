from __future__ import annotations

from typing import Any

from .trace import compact_state


def run_start_event(mode: str, valid: bool, issues: list[dict[str, Any]], input_state: dict[str, Any]) -> dict[str, Any]:
    return {
        "event": "run_start",
        "mode": mode,
        "valid": valid,
        "issues": issues,
        "inputState": input_state,
    }


def validation_failed_run_end_event(mode: str, valid: bool, issues: list[dict[str, Any]], input_state: dict[str, Any]) -> dict[str, Any]:
    return {
        "event": "run_end",
        "mode": mode,
        "valid": valid,
        "issues": issues,
        "trace": [],
        "outputState": dict(input_state),
        "status": "failed",
    }


def node_start_event(node: Any, input_state: dict[str, Any]) -> dict[str, Any]:
    return {
        "event": "node_start",
        "nodeId": node.id,
        "type": str(node.type),
        "label": node.label,
        "inputState": compact_state(input_state),
    }


def node_end_event(trace_item: dict[str, Any], output_state: dict[str, Any]) -> dict[str, Any]:
    return {
        "event": "node_end",
        "traceItem": trace_item,
        "outputState": compact_state(output_state),
    }


def run_end_event(trace: list[dict[str, Any]], output_state: dict[str, Any], status: str = "", pending_approval: dict[str, Any] | None = None) -> dict[str, Any]:
    event: dict[str, Any] = {
        "event": "run_end",
        "trace": trace,
        "outputState": compact_state(output_state),
    }
    if status:
        event["status"] = status
    if pending_approval is not None:
        event["pendingApproval"] = pending_approval
    return event
