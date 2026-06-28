from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from app.ir.schemas import NodeIR, NodeType, ProjectIR
from app.project_store import read_project
from app.runtime_environment import default_runtime_environment, resolve_runtime_environment
from app.runner import model_runtime
from app.runner.common import render_json_object
from app.runner.context import (
    AgentRuntimeConfig,
    ExecutionContext,
    ExecutionServices,
    McpRuntimeConfig,
    ModelRuntimeConfig,
    RunMode,
    RuntimeEnvironment,
    SkillRuntimeConfig,
    ToolRuntimeConfig,
    result_tuple,
)
from app.runner.events import node_end_event, node_start_event, run_end_event
from app.runner.graph_runtime import (
    error_execution_target,
    first_execution_target,
    human_approval_actions,
    next_execution_target,
)
from app.runner.policy import (
    HumanApprovalPause,
    NodePolicyError,
    format_error,
    run_node_with_policy,
    run_stream_node_with_policy,
    runtime_error_payload,
    trace_meta_from_exception,
)
from app.runner.resources import (
    agent_configs_by_id,
    enabled_skills_by_id,
    mcp_configs_by_id,
    tool_configs_by_id,
)
from app.runner.trace import compact_state, compact_value, data_shaping_trace_meta, node_trace_item, runtime_trace_item
from app.runner.data_runtime import json_object_list, resolve_input_mappings, truthy

MAX_STEPS = 80
MAX_AGENT_CALL_DEPTH = 3


def _child_trace_items_from_exception(exc: Exception) -> list[dict[str, Any]]:
    for candidate in (exc, getattr(exc, "original", None)):
        child_trace = getattr(candidate, "child_trace", None)
        if isinstance(child_trace, list):
            return [item for item in child_trace if isinstance(item, dict)]
    return []


def run_project_preview(
    project: ProjectIR,
    input_state: dict[str, Any],
    mode: RunMode = "dry",
    model_config: ModelRuntimeConfig = None,
    runtime_environment: RuntimeEnvironment = None,
    agent_depth: int = 0,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    return walk_project(
        project,
        normalize_input(input_state),
        mode,
        normalize_model_config(model_config),
        normalize_runtime_environment(runtime_environment),
        agent_depth,
    )


def resume_project_preview(
    project: ProjectIR,
    current_state: dict[str, Any],
    approval_node_id: str,
    action: str,
    comment: str = "",
    mode: RunMode = "live",
    model_config: ModelRuntimeConfig = None,
    runtime_environment: RuntimeEnvironment = None,
    agent_depth: int = 0,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    return resume_project(
        project,
        normalize_input(current_state),
        approval_node_id,
        action,
        comment,
        mode,
        normalize_model_config(model_config),
        normalize_runtime_environment(runtime_environment),
        agent_depth,
    )


def iter_project_preview_events(
    project: ProjectIR,
    input_state: dict[str, Any],
    mode: RunMode = "dry",
    model_config: ModelRuntimeConfig = None,
    runtime_environment: RuntimeEnvironment = None,
    agent_depth: int = 0,
):
    yield from walk_project_events(
        project,
        normalize_input(input_state),
        mode,
        normalize_model_config(model_config),
        normalize_runtime_environment(runtime_environment),
        agent_depth,
    )


def walk_project(
    project: ProjectIR,
    input_state: dict[str, Any],
    mode: RunMode,
    model_config: ModelRuntimeConfig,
    runtime_environment: RuntimeEnvironment,
    agent_depth: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    nodes = {node.id: node for node in project.nodes}
    skills = enabled_skills_by_id(project)
    tools = tool_configs_by_id(project)
    mcp_servers = mcp_configs_by_id(project)
    agents = agent_configs_by_id(project)
    outgoing: dict[str, list] = {}
    for edge in project.edges:
        outgoing.setdefault(edge.source, []).append(edge)

    start = next((node for node in project.nodes if node.type == NodeType.START), None)
    if not start:
        return [], dict(input_state)

    state = dict(input_state)
    trace: list[dict[str, Any]] = []
    current = first_execution_target(outgoing.get(start.id, []))
    visited = 0
    while current and current in nodes and visited < MAX_STEPS:
        visited += 1
        node = nodes[current]
        before = dict(state)
        started = time.perf_counter()
        handled_error_target: str | None = None
        child_trace_items: list[dict[str, Any]] = []
        trace_meta: dict[str, Any] = {}
        try:
            delta, detail, trace_meta = execute_node_with_policy(node, project, state, mode, model_config, runtime_environment, skills, tools, mcp_servers, agents, agent_depth)
            state.update(delta)
            status = "ok"
        except HumanApprovalPause as pause:
            approval = dict(pause.approval)
            trace_item = node_trace_item(
                node,
                "ok",
                "等待人工审批",
                round((time.perf_counter() - started) * 1000, 2),
                before,
                {},
                pause=True,
                approval=approval,
            )
            trace.append(trace_item)
            state["_glg_run_status"] = "paused"
            state["_glg_pending_approval"] = approval
            return trace, state
        except Exception as exc:
            handled_error_target = error_execution_target(node, outgoing)
            child_trace_items = _child_trace_items_from_exception(exc)
            trace_meta = trace_meta_from_exception(exc)
            if handled_error_target:
                delta = {"last_error": runtime_error_payload(node, exc)}
                state.update(delta)
                detail = f"{format_error(exc)}；已转入 error 分支。"
                status = "ok"
            else:
                delta = {}
                detail = format_error(exc)
                status = "error"

        trace.extend(child_trace_items)
        trace.append(node_trace_item(node, status, detail, round((time.perf_counter() - started) * 1000, 2), before, delta, **trace_meta))
        if status == "error" or node.type == NodeType.DIRECT_REPLY:
            break

        current = handled_error_target or next_execution_target(node, nodes, outgoing, state)

    if visited >= MAX_STEPS:
        trace.append(runtime_trace_item("运行预览", f"路径超过 {MAX_STEPS} 步，可能存在循环。", state))
    return trace, state


def resume_project(
    project: ProjectIR,
    state: dict[str, Any],
    approval_node_id: str,
    action: str,
    comment: str,
    mode: RunMode,
    model_config: ModelRuntimeConfig,
    runtime_environment: RuntimeEnvironment,
    agent_depth: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    nodes = {node.id: node for node in project.nodes}
    node = nodes.get(approval_node_id)
    if node is None or node.type != NodeType.HUMAN_APPROVAL:
        raise RuntimeError("待恢复节点不是 Human Approval。")
    outgoing: dict[str, list] = {}
    for edge in project.edges:
        outgoing.setdefault(edge.source, []).append(edge)
    available_actions = human_approval_actions(node, outgoing)
    fallback = str(node.config.get("fallback", "rejected") or "rejected").strip() or "rejected"
    normalized_action = action if action in available_actions else fallback
    if normalized_action not in available_actions:
        normalized_action = available_actions[0] if available_actions else "rejected"
    action_field = str(node.config.get("actionField", "approval_action"))
    output_field = str(node.config.get("outputField", "approval_result"))
    approval_result = {
        "action": normalized_action,
        "comment": comment,
        "approved": normalized_action == "approved",
        "status": "resumed",
        "resumedAt": datetime.now(timezone.utc).isoformat(),
    }
    before = dict(state)
    state[action_field] = normalized_action
    state[output_field] = approval_result
    state.pop("_glg_run_status", None)
    state.pop("_glg_pending_approval", None)
    trace: list[dict[str, Any]] = [
        node_trace_item(
            node,
            "ok",
            f"人工审批已提交：{normalized_action}",
            0,
            before,
            {action_field: normalized_action, output_field: approval_result},
            approval={
                "nodeId": node.id,
                "nodeLabel": node.label,
                "action": normalized_action,
                "comment": comment,
                "availableActions": available_actions,
                "defaultAction": str(node.config.get("defaultAction", available_actions[0] if available_actions else "approved") or "approved"),
                "actionField": action_field,
                "outputField": output_field,
                "resumedAt": approval_result["resumedAt"],
            },
        )
    ]
    skills = enabled_skills_by_id(project)
    tools = tool_configs_by_id(project)
    mcp_servers = mcp_configs_by_id(project)
    agents = agent_configs_by_id(project)
    current = next_execution_target(node, nodes, outgoing, state)
    visited = 0
    while current and current in nodes and visited < MAX_STEPS:
        visited += 1
        current_node = nodes[current]
        before = dict(state)
        started = time.perf_counter()
        handled_error_target: str | None = None
        trace_meta: dict[str, Any] = {}
        try:
            delta, detail, trace_meta = execute_node_with_policy(current_node, project, state, mode, model_config, runtime_environment, skills, tools, mcp_servers, agents, agent_depth)
            state.update(delta)
            status = "ok"
        except HumanApprovalPause as pause:
            approval = dict(pause.approval)
            trace.append(
                node_trace_item(
                    current_node,
                    "ok",
                    "等待人工审批",
                    round((time.perf_counter() - started) * 1000, 2),
                    before,
                    {},
                    pause=True,
                    approval=approval,
                )
            )
            state["_glg_run_status"] = "paused"
            state["_glg_pending_approval"] = approval
            return trace, state
        except Exception as exc:
            handled_error_target = error_execution_target(current_node, outgoing)
            trace_meta = trace_meta_from_exception(exc)
            if handled_error_target:
                delta = {"last_error": runtime_error_payload(current_node, exc)}
                state.update(delta)
                detail = f"{format_error(exc)}；已转入 error 分支。"
                status = "ok"
            else:
                delta = {}
                detail = format_error(exc)
                status = "error"
        trace.append(node_trace_item(current_node, status, detail, round((time.perf_counter() - started) * 1000, 2), before, delta, **trace_meta))
        if status == "error" or current_node.type == NodeType.DIRECT_REPLY:
            break
        current = handled_error_target or next_execution_target(current_node, nodes, outgoing, state)
    if visited >= MAX_STEPS:
        trace.append(runtime_trace_item("运行恢复", f"路径超过 {MAX_STEPS} 步，可能存在循环。", state))
    return trace, state


def walk_project_events(
    project: ProjectIR,
    input_state: dict[str, Any],
    mode: RunMode,
    model_config: ModelRuntimeConfig,
    runtime_environment: RuntimeEnvironment,
    agent_depth: int,
):
    nodes = {node.id: node for node in project.nodes}
    skills = enabled_skills_by_id(project)
    tools = tool_configs_by_id(project)
    mcp_servers = mcp_configs_by_id(project)
    agents = agent_configs_by_id(project)
    outgoing: dict[str, list] = {}
    for edge in project.edges:
        outgoing.setdefault(edge.source, []).append(edge)

    start = next((node for node in project.nodes if node.type == NodeType.START), None)
    state = dict(input_state)
    trace: list[dict[str, Any]] = []
    if not start:
        yield run_end_event(trace, state)
        return

    current = first_execution_target(outgoing.get(start.id, []))
    visited = 0
    while current and current in nodes and visited < MAX_STEPS:
        visited += 1
        node = nodes[current]
        before = dict(state)
        yield node_start_event(node, before)
        started = time.perf_counter()
        handled_error_target: str | None = None
        child_trace_items: list[dict[str, Any]] = []
        trace_meta: dict[str, Any] = {}
        try:
            if mode == "live" and node.type == NodeType.PARALLEL_TOOLS:
                def run_parallel_tools_stream():
                    from app.runner.registry import execute_events

                    ctx = execution_context(project, "live", model_config, runtime_environment, skills, tools, mcp_servers, agents, agent_depth)
                    stream_result = yield from execute_events(node, state, ctx)
                    if isinstance(stream_result, tuple) and len(stream_result) == 3:
                        return stream_result
                    stream_delta, stream_detail = stream_result
                    return stream_delta, stream_detail, []

                delta, detail, child_trace_items, trace_meta = yield from execute_stream_node_with_policy(node, state, run_parallel_tools_stream)
            elif mode == "live" and node.type == NodeType.FOR_EACH:
                def run_for_each_stream():
                    from app.runner.registry import execute_events

                    ctx = execution_context(project, "live", model_config, runtime_environment, skills, tools, mcp_servers, agents, agent_depth)
                    return (yield from execute_events(node, state, ctx))

                delta, detail, child_trace_items, trace_meta = yield from execute_stream_node_with_policy(node, state, run_for_each_stream)
            else:
                delta, detail, trace_meta = execute_node_with_policy(node, project, state, mode, model_config, runtime_environment, skills, tools, mcp_servers, agents, agent_depth)
            state.update(delta)
            status = "ok"
        except HumanApprovalPause as pause:
            approval = dict(pause.approval)
            trace_item = node_trace_item(
                node,
                "ok",
                "等待人工审批",
                round((time.perf_counter() - started) * 1000, 2),
                before,
                {},
                pause=True,
                approval=approval,
            )
            trace.append(trace_item)
            yield node_end_event(trace_item, state)
            yield run_end_event(trace, state, status="paused", pending_approval=approval)
            return
        except Exception as exc:
            handled_error_target = error_execution_target(node, outgoing)
            child_trace_items = _child_trace_items_from_exception(exc)
            trace_meta = trace_meta_from_exception(exc)
            if handled_error_target:
                delta = {"last_error": runtime_error_payload(node, exc)}
                state.update(delta)
                detail = f"{format_error(exc)}；已转入 error 分支。"
                status = "ok"
            else:
                delta = {}
                detail = format_error(exc)
                status = "error"

        trace_item = node_trace_item(node, status, detail, round((time.perf_counter() - started) * 1000, 2), before, delta, **trace_meta)
        trace.extend(child_trace_items)
        trace.append(trace_item)
        yield node_end_event(trace_item, state)
        if status == "error" or node.type == NodeType.DIRECT_REPLY:
            break

        current = handled_error_target or next_execution_target(node, nodes, outgoing, state)

    if visited >= MAX_STEPS:
        trace_item = runtime_trace_item("运行预览", f"路径超过 {MAX_STEPS} 步，可能存在循环。", state)
        trace.append(trace_item)
        yield node_end_event(trace_item, state)

    yield run_end_event(trace, state)


def execute_node(
    node: NodeIR,
    project: ProjectIR,
    state: dict[str, Any],
    mode: RunMode,
    model_config: ModelRuntimeConfig,
    runtime_environment: RuntimeEnvironment,
    skills: SkillRuntimeConfig,
    tools: ToolRuntimeConfig,
    mcp_servers: McpRuntimeConfig,
    agents: AgentRuntimeConfig,
    agent_depth: int,
) -> tuple[dict[str, Any], str]:
    if mode == "dry":
        if node.type == NodeType.CUSTOM_FUNCTION:
            field = str(node.config.get("outputField", f"{node.type}_result"))
            return {field: f"[dry-run] {node.label}"}, f"模拟输出到 state.{field}"
        from app.runner.registry import execute_dry

        ctx = execution_context(project, "dry", model_config, runtime_environment, skills, tools, mcp_servers, agents, agent_depth)
        return result_tuple(execute_dry(node, state, ctx))
    return execute_live_node(node, project, state, model_config, runtime_environment, skills, tools, mcp_servers, agents, agent_depth)


def execute_node_with_policy(
    node: NodeIR,
    project: ProjectIR,
    state: dict[str, Any],
    mode: RunMode,
    model_config: ModelRuntimeConfig,
    runtime_environment: RuntimeEnvironment,
    skills: SkillRuntimeConfig,
    tools: ToolRuntimeConfig,
    mcp_servers: McpRuntimeConfig,
    agents: AgentRuntimeConfig,
    agent_depth: int,
) -> tuple[dict[str, Any], str, dict[str, Any]]:
    return run_node_with_policy(
        node,
        state,
        lambda: execute_node(node, project, state, mode, model_config, runtime_environment, skills, tools, mcp_servers, agents, agent_depth),
        runtime_error_payload=runtime_error_payload,
        fallback_policy_delta=fallback_policy_delta,
        data_shaping_trace_meta=build_data_shaping_trace_meta,
    )


def execute_stream_node_with_policy(
    node: NodeIR,
    state: dict[str, Any],
    stream_factory,
):
    return (
        yield from run_stream_node_with_policy(
            node,
            state,
            stream_factory,
            runtime_error_payload=runtime_error_payload,
            fallback_policy_delta=fallback_policy_delta,
        )
    )


def execution_context(
    project: ProjectIR,
    mode: RunMode,
    model_config: ModelRuntimeConfig,
    runtime_environment: RuntimeEnvironment,
    skills: SkillRuntimeConfig,
    tools: ToolRuntimeConfig,
    mcp_servers: McpRuntimeConfig,
    agents: AgentRuntimeConfig,
    agent_depth: int,
) -> ExecutionContext:
    return ExecutionContext(
        project=project,
        mode=mode,
        model_config=model_config,
        runtime_environment=runtime_environment,
        skills=skills,
        tools=tools,
        mcp_servers=mcp_servers,
        agents=agents,
        agent_depth=agent_depth,
        services=execution_services(project, model_config, runtime_environment, skills, tools, mcp_servers, agents, agent_depth),
    )


def execution_services(
    project: ProjectIR,
    model_config: ModelRuntimeConfig,
    runtime_environment: RuntimeEnvironment,
    skills: SkillRuntimeConfig,
    tools: ToolRuntimeConfig,
    mcp_servers: McpRuntimeConfig,
    agents: AgentRuntimeConfig,
    agent_depth: int,
) -> ExecutionServices:
    def execute_child_with_policy(child: NodeIR, child_state: dict[str, Any], mode: RunMode = "live"):
        return execute_node_with_policy(child, project, child_state, mode, model_config, runtime_environment, skills, tools, mcp_servers, agents, agent_depth)

    def execute_child(child: NodeIR, child_state: dict[str, Any], mode: RunMode = "live"):
        return execute_node(child, project, child_state, mode, model_config, runtime_environment, skills, tools, mcp_servers, agents, agent_depth)

    def execute_child_events(child: NodeIR, child_state: dict[str, Any], mode: RunMode = "live"):
        from app.runner.registry import execute_events

        ctx = execution_context(project, mode, model_config, runtime_environment, skills, tools, mcp_servers, agents, agent_depth)
        return execute_events(child, child_state, ctx)

    def run_project_by_id(project_id: str, child_input: dict[str, Any], child_model_config: ModelRuntimeConfig, child_runtime_environment: RuntimeEnvironment, child_agent_depth: int):
        child_project = read_project(project_id)
        trace, output_state = walk_project(
            child_project,
            normalize_input(child_input),
            "live",
            normalize_model_config(child_model_config),
            normalize_runtime_environment(child_runtime_environment),
            child_agent_depth,
        )
        return child_project, trace, output_state

    return ExecutionServices(
        execute_node=execute_child,
        execute_node_with_policy=execute_child_with_policy,
        execute_node_events=execute_child_events,
        run_project=run_project_by_id,
        next_execution_target=next_execution_target,
        error_execution_target=error_execution_target,
        trace_meta_from_exception=trace_meta_from_exception,
        compact_state=compact_state,
        compact_value=compact_value,
        max_steps=MAX_STEPS,
    )


def execute_live_node(
    node: NodeIR,
    project: ProjectIR,
    state: dict[str, Any],
    model_config: ModelRuntimeConfig,
    runtime_environment: RuntimeEnvironment,
    skills: SkillRuntimeConfig,
    tools: ToolRuntimeConfig,
    mcp_servers: McpRuntimeConfig,
    agents: AgentRuntimeConfig,
    agent_depth: int,
) -> tuple[dict[str, Any], str]:
    from app.runner.registry import execute_live

    ctx = execution_context(project, "live", model_config, runtime_environment, skills, tools, mcp_servers, agents, agent_depth)
    try:
        return result_tuple(execute_live(node, state, ctx))
    except RuntimeError:
        raise
    except Exception as exc:
        raise exc


def normalize_model_config(config: ModelRuntimeConfig) -> ModelRuntimeConfig:
    return model_runtime.normalize_model_config(config)


def normalize_runtime_environment(runtime_environment: RuntimeEnvironment) -> dict[str, Any]:
    if runtime_environment:
        return resolve_runtime_environment(runtime_environment)
    return default_runtime_environment().model_dump(by_alias=True)


def fallback_policy_delta(node: NodeIR, state: dict[str, Any], policy: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    try:
        delta = render_json_object(str(policy.get("fallbackOutputJson") or "{}"), state, "fallbackOutputJson")
    except RuntimeError as exc:
        raise NodePolicyError(node, exc, runtime_error_payload(node, exc), [], policy) from exc
    if policy.get("errorOutputField"):
        delta[str(policy["errorOutputField"])] = payload
    return delta


def build_data_shaping_trace_meta(node: NodeIR, state: dict[str, Any], delta: dict[str, Any]) -> dict[str, Any]:
    return data_shaping_trace_meta(
        node,
        state,
        delta,
        json_object_list=json_object_list,
        resolve_input_mappings=resolve_input_mappings,
        truthy=truthy,
    )


def normalize_input(input_state: dict[str, Any]) -> dict[str, Any]:
    state = dict(input_state)
    if "messages" not in state:
        if "message" in state:
            state["messages"] = state["message"]
        elif "input" in state:
            state["messages"] = state["input"]
    return state
