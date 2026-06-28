from __future__ import annotations

from typing import Any

from app.ir.schemas import NodeIR

from ..common import agent_state_prompt, json_object_list, json_string_list, positive_int, render_template
from ..context import ExecutionContext
from ..model_runtime import effective_model_config, resolve_node_model
from ..tool_runtime.registry import run_tools_agent_session, selected_tool_configs


def execute_live(node: NodeIR, state: dict[str, Any], ctx: ExecutionContext):
    return execute_tool_node(node, state, ctx.model_config, ctx.runtime_environment, ctx.tools)


def execute_dry(node: NodeIR, state: dict[str, Any], ctx: ExecutionContext):
    config = node.config
    field = str(config.get("outputField", "tool_result"))
    selected_tools = selected_tool_configs(config, ctx.tools)
    return {
        field: f"[dry-run] {node.label} 可在 {len(selected_tools)} 个 Tool 中自主选择并多轮调用",
        f"{field}_tool_calls": [
            {"tool": tool.get("name") or tool.get("id"), "status": "registered"} for tool in selected_tools
        ],
    }, f"模拟 Tools Agent 注册 {len(selected_tools)} 个 Tool，输出到 state.{field}"


def execute_tool_node(
    node: NodeIR,
    state: dict[str, Any],
    model_config: dict[str, Any] | None,
    runtime_environment: dict[str, Any] | None,
    tools: dict[str, dict[str, Any]],
):
    config = node.config
    source = str(config.get("source", "")).strip().lower()
    legacy_single_tool = not json_string_list(config.get("toolIdsJson")) and not json_object_list(config.get("toolRegistryJson"))
    if legacy_single_tool and (source == "http" or str(config.get("url", "")).strip() or str(config.get("mockResponseJson", "")).strip()):
        from app.runner.nodes.http import execute_http_node

        return execute_http_node(node, state)
    output_field = str(config.get("outputField", f"{node.id}_result"))
    selected_tools = selected_tool_configs(config, tools)
    if not selected_tools and legacy_single_tool:
        return {
            output_field: {
                "tool": config.get("toolName", node.label),
                "source": source or "declarative",
                "status": "configured",
            }
        }, f"声明式 Tool 已记录到 state.{output_field}"
    if not selected_tools:
        raise RuntimeError("Tools 节点没有选择任何已配置 Tool。")

    effective_config = effective_model_config(config, model_config)
    provider, model = resolve_node_model(config, model_config, "openai", "gpt-4.1-mini")
    max_iterations = min(positive_int(config.get("maxIterations", 4), 4), 12)
    system_prompt = render_template(str(config.get("systemPrompt", "")), state).strip()
    user_prompt = render_template(str(config.get("userPrompt") or agent_state_prompt(state)), state)
    final_answer, calls = run_tools_agent_session(
        provider,
        model,
        effective_config,
        selected_tools,
        system_prompt,
        user_prompt,
        max_iterations,
        runtime_environment,
    )

    return {
        output_field: final_answer,
        f"{output_field}_tool_calls": calls,
    }, f"Tools Agent 注册 {len(selected_tools)} 个 Tool，执行 {len(calls)} 次工具调用，输出到 state.{output_field}"
