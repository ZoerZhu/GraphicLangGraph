from __future__ import annotations

from typing import Any

from app.ir.schemas import NodeIR

from .. import model_runtime
from ..common import agent_state_prompt, json_object_list, json_string_list, positive_int, render_template
from ..context import ExecutionContext
from ..resources import agent_tool_configs, mcp_agent_tool_configs, selected_agent_configs, selected_mcp_server_configs, selected_skill_configs
from ..skills_runtime import append_selected_skills
from ..tool_runtime.registry import run_tools_agent_session, selected_tool_configs


def execute_live(node: NodeIR, state: dict[str, Any], ctx: ExecutionContext):
    return execute_agent(node, state, ctx)


def execute_dry(node: NodeIR, state: dict[str, Any], ctx: ExecutionContext):
    field = str(node.config.get("outputField", "agent_result"))
    return {field: f"[dry-run] {node.label} 将作为 Agent 执行"}, f"模拟 Agent 输出到 state.{field}"


def execute_agent(node: NodeIR, state: dict[str, Any], ctx: ExecutionContext):
    config = node.config
    effective_config = model_runtime.effective_model_config(config, ctx.model_config)
    provider, model = model_runtime.resolve_node_model(config, ctx.model_config, "openai", "gpt-4.1-mini")
    system_prompt = render_template(str(config.get("systemPrompt", "")), state).strip()
    selected_skills = selected_skill_configs(config, ctx.skills)
    system_prompt = append_selected_skills(system_prompt, selected_skills)
    user_prompt = str(config.get("userPrompt", "")).strip()
    if user_prompt:
        user_text = render_template(user_prompt, state)
    else:
        user_text = agent_state_prompt(state)
    selected_tools = selected_tool_configs(config, ctx.tools)
    selected_mcp_servers = selected_mcp_server_configs(config, ctx.mcp_servers)
    selected_agents = selected_agent_configs(config, ctx.agents)
    if selected_tools or selected_mcp_servers or selected_agents:
        max_iterations = min(positive_int(config.get("maxIterations", 4), 4), 12)
        mcp_tools = mcp_agent_tool_configs(selected_mcp_servers, ctx.runtime_environment)
        agent_tools = agent_tool_configs(selected_agents, ctx.project)
        registered_tools = [*selected_tools, *mcp_tools, *agent_tools]
        if (json_string_list(config.get("toolIdsJson")) or json_object_list(config.get("toolRegistryJson"))) and not selected_tools:
            raise RuntimeError("Agent 已选择 Tool，但没有可用 Tool。")
        if selected_mcp_servers and not mcp_tools:
            raise RuntimeError("Agent 已选择 MCP Server，但没有可用 MCP Tool。")
        if selected_agents and not agent_tools:
            raise RuntimeError("Agent 已选择子 Agent，但没有可用 Agent Tool。")
        final_answer, calls = run_tools_agent_session(
            provider,
            model,
            effective_config,
            registered_tools,
            system_prompt,
            user_text,
            max_iterations,
            ctx.runtime_environment,
            {
                "projectId": ctx.project.project.id,
                "projectName": ctx.project.project.name,
                "state": state,
                "agentDepth": ctx.agent_depth,
                "modelConfig": effective_config,
                "runProject": ctx.services.run_project if ctx.services else None,
            },
        )
        output_field = str(config.get("outputField", f"{node.id}_result"))
        skill_hint = f"，注入 {len(selected_skills)} 个 Skill" if selected_skills else ""
        result = {
            output_field: final_answer,
            f"{output_field}_tool_calls": [call for call in calls if str(call.get("source") or "") not in {"mcp", "agent"}],
            f"{output_field}_mcp_tool_calls": [call for call in calls if str(call.get("source") or "") == "mcp"],
            f"{output_field}_agent_tool_calls": [call for call in calls if str(call.get("source") or "") == "agent"],
        }
        return result, f"真实调用 Agent 模型 {provider}/{model}{skill_hint}，注册 {len(registered_tools)} 个工具，执行 {len(calls)} 次调用，输出到 state.{output_field}"
    messages: list[tuple[str, str]] = []
    if system_prompt:
        messages.append(("system", system_prompt))
    messages.append(("user", user_text))
    response = model_runtime.call_chat_model(provider, model, messages, effective_config)
    content = getattr(response, "content", str(response))
    output_field = str(config.get("outputField", f"{node.id}_result"))
    tools = str(config.get("tools", "")).strip()
    tool_hint = f"，参考工具/前置结果：{tools}" if tools else ""
    skill_hint = f"，注入 {len(selected_skills)} 个 Skill" if selected_skills else ""
    return {output_field: content}, f"真实调用 Agent 模型 {provider}/{model}{tool_hint}{skill_hint}，输出到 state.{output_field}"
