from __future__ import annotations

from typing import Any

from app.ir.schemas import NodeIR

from .. import engine
from ..common import render_template, state_value_to_text
from ..context import ExecutionContext
from ..tool_runtime.registry import invoke_agent_tool


def execute_live(node: NodeIR, state: dict[str, Any], ctx: ExecutionContext):
    config = node.config
    output_field = str(config.get("outputField") or "agent_ref_result").strip() or "agent_ref_result"
    project_id = str(config.get("agentProjectId") or "").strip()
    if not project_id:
        raise RuntimeError("Agent Ref 未绑定 Agent。")
    if project_id == ctx.project.project.id:
        raise RuntimeError("禁止 Agent Ref 调用当前项目自身。")
    instruction = render_template(str(config.get("instruction") or ""), state).strip()
    input_text = instruction or state_value_to_text(state.get("messages") or state.get("chat")) or engine._agent_state_prompt(state)
    result = invoke_agent_tool(
        {
            "agentId": str(config.get("agentId") or project_id),
            "agentName": str(config.get("agentName") or node.label or project_id),
            "projectId": project_id,
        },
        {"input": input_text, "statePatch": {}},
        ctx.model_config,
        ctx.runtime_environment,
        {"projectId": ctx.project.project.id, "projectName": ctx.project.project.name, "state": state, "agentDepth": ctx.agent_depth},
    )
    detail = f"真实调用 Agent Ref「{result.get('agentName')}」({config.get('protocol', 'handoff')})，输出到 state.{output_field}"
    return {output_field: result}, detail


def execute_dry(node: NodeIR, state: dict[str, Any], ctx: ExecutionContext):
    field = str(node.config.get("outputField", f"{node.type}_result"))
    return {field: f"[dry-run] {node.label}"}, f"模拟输出到 state.{field}"
