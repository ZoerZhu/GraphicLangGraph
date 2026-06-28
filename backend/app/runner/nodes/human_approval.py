from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.ir.schemas import NodeIR, ProjectIR

from ..common import compact_state, render_template
from ..context import ExecutionContext
from ..graph_runtime import human_approval_actions
from ..policy import HumanApprovalPause


def execute_human_approval(node: NodeIR, project: ProjectIR, state: dict[str, Any]):
    config = node.config
    action_field = str(config.get("actionField", "approval_action"))
    output_field = str(config.get("outputField", "approval_result"))
    outgoing: dict[str, list] = {}
    for edge in project.edges:
        outgoing.setdefault(edge.source, []).append(edge)
    available_actions = human_approval_actions(node, outgoing)
    fallback = str(config.get("fallback", "rejected") or "rejected").strip() or "rejected"
    provided_action = str(state.get(action_field) or "").strip()
    if provided_action:
        normalized_action = provided_action if provided_action in available_actions else fallback
        if normalized_action not in available_actions:
            normalized_action = available_actions[0] if available_actions else "rejected"
        approval_result = {
            "action": normalized_action,
            "approved": normalized_action == "approved",
            "status": "auto",
            "submittedAt": datetime.now(timezone.utc).isoformat(),
        }
        return {action_field: normalized_action, output_field: approval_result}, f"使用运行输入自动审批：{normalized_action}"
    prompt = render_template(str(config.get("prompt", "")), state)
    approval = {
        "nodeId": node.id,
        "nodeLabel": node.label,
        "prompt": prompt,
        "actions": available_actions,
        "defaultAction": str(config.get("defaultAction", available_actions[0] if available_actions else "approved") or "approved"),
        "actionField": action_field,
        "outputField": output_field,
        "state": compact_state(state),
    }
    raise HumanApprovalPause(node, state, approval)


def execute_live(node: NodeIR, state: dict[str, Any], ctx: ExecutionContext):
    return execute_human_approval(node, ctx.project, state)


def execute_dry(node: NodeIR, state: dict[str, Any], ctx: ExecutionContext):
    config = node.config
    action_field = str(config.get("actionField", "approval_action"))
    action = str(state.get(action_field) or config.get("defaultAction", "approved"))
    output_field = str(config.get("outputField", "approval_result"))
    return {
        action_field: action,
        output_field: {"action": action, "status": "dry-run"},
    }, f"模拟人工审批动作 {action}"
