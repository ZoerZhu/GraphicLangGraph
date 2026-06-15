from __future__ import annotations

import asyncio
import importlib.util
import inspect
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Literal
from urllib import request as urllib_request
from urllib.error import URLError

import httpx

from app.config import ROOT_DIR, WORKSPACE_TOOLS_FILE
from app.ir.schemas import EdgeKind, NodeIR, NodeType, ProjectIR


RunMode = Literal["dry", "live"]
ModelRuntimeConfig = dict[str, Any] | None
SkillRuntimeConfig = dict[str, dict[str, Any]]
ToolRuntimeConfig = dict[str, dict[str, Any]]

TEMPLATE_RE = re.compile(r"{{\s*state\.([a-zA-Z_][a-zA-Z0-9_]*)\s*}}")
TEXT_SUFFIXES = {".md", ".markdown", ".txt"}
MAX_STEPS = 80
OPENAI_COMPATIBLE_PROVIDERS = {
    "custom",
    "openai_compatible",
    "deepseek",
    "moonshot",
    "qwen",
    "zhipu",
    "minimax",
    "baichuan",
    "groq",
    "ollama",
}
OPENAI_COMPATIBLE_BASE_URLS = {
    "deepseek": "https://api.deepseek.com",
    "moonshot": "https://api.moonshot.cn/v1",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "zhipu": "https://open.bigmodel.cn/api/paas/v4/",
    "minimax": "https://api.minimax.chat/v1",
    "baichuan": "https://api.baichuan-ai.com/v1",
    "groq": "https://api.groq.com/openai/v1",
    "ollama": "http://localhost:11434/v1",
}
PROVIDER_ALIASES = {
    "google": "google_genai",
}


class LiveRunUnsupportedError(RuntimeError):
    pass


def run_project_preview(
    project: ProjectIR,
    input_state: dict[str, Any],
    mode: RunMode = "dry",
    model_config: ModelRuntimeConfig = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    return _walk_project(project, _normalize_input(input_state), mode, _normalize_model_config(model_config))


def iter_project_preview_events(
    project: ProjectIR,
    input_state: dict[str, Any],
    mode: RunMode = "dry",
    model_config: ModelRuntimeConfig = None,
):
    yield from _walk_project_events(project, _normalize_input(input_state), mode, _normalize_model_config(model_config))


def _walk_project(
    project: ProjectIR,
    input_state: dict[str, Any],
    mode: RunMode,
    model_config: ModelRuntimeConfig,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    nodes = {node.id: node for node in project.nodes}
    skills = _enabled_skills_by_id(project)
    tools = _tool_configs_by_id(project)
    outgoing: dict[str, list] = {}
    for edge in project.edges:
        outgoing.setdefault(edge.source, []).append(edge)

    start = next((node for node in project.nodes if node.type == NodeType.START), None)
    if not start:
        return [], dict(input_state)

    state = dict(input_state)
    trace: list[dict[str, Any]] = []
    current = _first_target(outgoing.get(start.id, []))
    visited = 0
    while current and current in nodes and visited < MAX_STEPS:
        visited += 1
        node = nodes[current]
        before = dict(state)
        started = time.perf_counter()
        try:
            delta, detail = _execute_node(node, state, mode, model_config, skills, tools)
            state.update(delta)
            status = "ok"
        except Exception as exc:  # Keep the preview response structured instead of surfacing a 500.
            delta = {}
            detail = _format_error(exc)
            status = "error"

        trace.append(
            {
                "nodeId": node.id,
                "type": str(node.type),
                "label": node.label,
                "status": status,
                "detail": detail,
                "durationMs": round((time.perf_counter() - started) * 1000, 2),
                "inputState": _compact_state(before),
                "outputDelta": _compact_state(delta),
            }
        )
        if status == "error" or node.type == NodeType.DIRECT_REPLY:
            break

        edges = outgoing.get(node.id, [])
        if not edges:
            break
        conditional_edges = [edge for edge in edges if edge.kind == EdgeKind.CONDITIONAL]
        if conditional_edges:
            handle = _choose_handle(node, state)
            current = _target_for_handle(conditional_edges, handle) or _first_target(conditional_edges)
        else:
            current = _first_target(edges)

    if visited >= MAX_STEPS:
        trace.append(
            {
                "nodeId": "__runtime__",
                "type": "custom_function",
                "label": "运行预览",
                "status": "error",
                "detail": f"路径超过 {MAX_STEPS} 步，可能存在循环。",
                "durationMs": 0,
                "inputState": _compact_state(state),
                "outputDelta": {},
            }
        )
    return trace, state


def _walk_project_events(
    project: ProjectIR,
    input_state: dict[str, Any],
    mode: RunMode,
    model_config: ModelRuntimeConfig,
):
    nodes = {node.id: node for node in project.nodes}
    skills = _enabled_skills_by_id(project)
    tools = _tool_configs_by_id(project)
    outgoing: dict[str, list] = {}
    for edge in project.edges:
        outgoing.setdefault(edge.source, []).append(edge)

    start = next((node for node in project.nodes if node.type == NodeType.START), None)
    state = dict(input_state)
    trace: list[dict[str, Any]] = []
    if not start:
        yield {
            "event": "run_end",
            "trace": trace,
            "outputState": _compact_state(state),
        }
        return

    current = _first_target(outgoing.get(start.id, []))
    visited = 0
    while current and current in nodes and visited < MAX_STEPS:
        visited += 1
        node = nodes[current]
        before = dict(state)
        yield {
            "event": "node_start",
            "nodeId": node.id,
            "type": str(node.type),
            "label": node.label,
            "inputState": _compact_state(before),
        }
        started = time.perf_counter()
        try:
            delta, detail = _execute_node(node, state, mode, model_config, skills, tools)
            state.update(delta)
            status = "ok"
        except Exception as exc:  # Keep streamed events structured instead of surfacing a 500.
            delta = {}
            detail = _format_error(exc)
            status = "error"

        trace_item = {
            "nodeId": node.id,
            "type": str(node.type),
            "label": node.label,
            "status": status,
            "detail": detail,
            "durationMs": round((time.perf_counter() - started) * 1000, 2),
            "inputState": _compact_state(before),
            "outputDelta": _compact_state(delta),
        }
        trace.append(trace_item)
        yield {
            "event": "node_end",
            "traceItem": trace_item,
            "outputState": _compact_state(state),
        }
        if status == "error" or node.type == NodeType.DIRECT_REPLY:
            break

        edges = outgoing.get(node.id, [])
        if not edges:
            break
        conditional_edges = [edge for edge in edges if edge.kind == EdgeKind.CONDITIONAL]
        if conditional_edges:
            handle = _choose_handle(node, state)
            current = _target_for_handle(conditional_edges, handle) or _first_target(conditional_edges)
        else:
            current = _first_target(edges)

    if visited >= MAX_STEPS:
        trace_item = {
            "nodeId": "__runtime__",
            "type": "custom_function",
            "label": "运行预览",
            "status": "error",
            "detail": f"路径超过 {MAX_STEPS} 步，可能存在循环。",
            "durationMs": 0,
            "inputState": _compact_state(state),
            "outputDelta": {},
        }
        trace.append(trace_item)
        yield {
            "event": "node_end",
            "traceItem": trace_item,
            "outputState": _compact_state(state),
        }

    yield {
        "event": "run_end",
        "trace": trace,
        "outputState": _compact_state(state),
    }


def _execute_node(
    node: NodeIR,
    state: dict[str, Any],
    mode: RunMode,
    model_config: ModelRuntimeConfig,
    skills: SkillRuntimeConfig,
    tools: ToolRuntimeConfig,
) -> tuple[dict[str, Any], str]:
    if mode == "dry":
        return _execute_dry_node(node, state, skills, tools)
    return _execute_live_node(node, state, model_config, skills, tools)


def _execute_dry_node(node: NodeIR, state: dict[str, Any], skills: SkillRuntimeConfig, tools: ToolRuntimeConfig) -> tuple[dict[str, Any], str]:
    config = node.config
    if node.type == NodeType.LLM:
        field = str(config.get("outputField", "final_answer"))
        return {field: f"[dry-run] {node.label} 将调用模型 {config.get('model', 'gpt-4.1-mini')}"}, f"模拟 LLM 输出到 state.{field}"
    if node.type == NodeType.AGENT:
        field = str(config.get("outputField", "agent_result"))
        return {field: f"[dry-run] {node.label} 将作为 Agent 执行"}, f"模拟 Agent 输出到 state.{field}"
    if node.type == NodeType.TOOL:
        field = str(config.get("outputField", "tool_result"))
        selected_tools = _selected_tool_configs(config, tools)
        return {
            field: f"[dry-run] {node.label} 可在 {len(selected_tools)} 个 Tool 中自主选择并多轮调用",
            f"{field}_tool_calls": [
                {"tool": tool.get("name") or tool.get("id"), "status": "registered"} for tool in selected_tools
            ],
        }, f"模拟 Tools Agent 注册 {len(selected_tools)} 个 Tool，输出到 state.{field}"
    if node.type == NodeType.RETRIEVER:
        field = str(config.get("outputField", "retrieved_context"))
        return {
            field: f"[dry-run] 从 {config.get('path', './knowledge')} 检索 top_k={config.get('topK', 4)}",
        }, f"模拟 Retriever 输出到 state.{field}"
    if node.type == NodeType.CONDITION:
        return {}, f"按 state.{config.get('field', 'intent')} 选择分支"
    if node.type == NodeType.AI_ROUTER:
        field = str(config.get("routeField", "route_key"))
        fallback = str(config.get("fallback", "other"))
        route = _infer_router_key(config, state) or fallback
        reason_field = str(config.get("reasonField", "route_reason"))
        return {field: route, reason_field: "dry-run router decision"}, f"模拟 AI Router 选择 {route}"
    if node.type == NodeType.HUMAN_APPROVAL:
        action_field = str(config.get("actionField", "approval_action"))
        action = str(state.get(action_field) or config.get("defaultAction", "approved"))
        output_field = str(config.get("outputField", "approval_result"))
        return {
            action_field: action,
            output_field: {"action": action, "status": "dry-run"},
        }, f"模拟人工审批动作 {action}"
    if node.type == NodeType.HTTP:
        field = str(config.get("outputField", "http_response"))
        return {field: {"url": config.get("url", ""), "status": "dry-run"}}, f"模拟 HTTP 输出到 state.{field}"
    if node.type == NodeType.DIRECT_REPLY:
        field = str(config.get("outputField", "final_answer"))
        return {field: state.get(field) or "[dry-run] Direct Reply"}, f"终止并返回 state.{field}"
    if node.type == NodeType.SKILL_NODE:
        return _execute_skill_node(node, skills, dry_run=True)
    if node.type in {NodeType.MCP_NODE, NodeType.AGENT_REF, NodeType.CUSTOM_FUNCTION}:
        field = str(config.get("outputField", f"{node.type}_result"))
        return {field: f"[dry-run] {node.label}"}, f"模拟输出到 state.{field}"
    return {}, "跳过未知节点"


def _execute_live_node(
    node: NodeIR,
    state: dict[str, Any],
    model_config: ModelRuntimeConfig,
    skills: SkillRuntimeConfig,
    tools: ToolRuntimeConfig,
) -> tuple[dict[str, Any], str]:
    config = node.config
    if node.type == NodeType.LLM:
        return _execute_live_llm(node, state, model_config)
    if node.type == NodeType.AGENT:
        return _execute_live_agent(node, state, model_config, skills)
    if node.type == NodeType.SKILL_NODE:
        return _execute_skill_node(node, skills, dry_run=False)
    if node.type == NodeType.TOOL:
        return _execute_live_tool(node, state, model_config, tools)
    if node.type == NodeType.RETRIEVER:
        return _execute_live_retriever(node, state)
    if node.type == NodeType.CONDITION:
        return {}, f"按 state.{config.get('field', 'intent')} 选择分支"
    if node.type == NodeType.AI_ROUTER:
        return _execute_live_ai_router(node, state, model_config)
    if node.type == NodeType.HUMAN_APPROVAL:
        return _execute_live_human_approval(node, state)
    if node.type == NodeType.HTTP:
        return _execute_live_http(node, state)
    if node.type == NodeType.DIRECT_REPLY:
        field = str(config.get("outputField", "final_answer"))
        content = render_template(str(config.get("template", "{{ state.final_answer }}")), state)
        return {field: content}, f"终止并返回 state.{field}"
    raise LiveRunUnsupportedError(f"真实运行 v1 暂不执行 {node.type} 节点；请改用 dry-run，或先使用 LLM/Retriever/Direct Reply 链路。")


def _execute_live_llm(node: NodeIR, state: dict[str, Any], model_config: ModelRuntimeConfig) -> tuple[dict[str, Any], str]:
    config = node.config
    provider, model = _resolve_node_model(config, model_config, "openai", "gpt-4.1-mini")
    system_prompt = render_template(str(config.get("systemPrompt", "")), state).strip()
    user_prompt = render_template(str(config.get("userPrompt", "{{ state.messages }}")), state).strip()
    messages: list[tuple[str, str]] = []
    if system_prompt:
        messages.append(("system", system_prompt))
    messages.append(("user", user_prompt or _state_value_to_text(state.get("messages", ""))))
    response = _call_chat_model(provider, model, messages, model_config)
    content = getattr(response, "content", str(response))
    output_field = str(config.get("outputField", f"{node.id}_output"))
    config_name = _runtime_value(model_config, "name")
    suffix = f"（{config_name}）" if config_name else ""
    return {output_field: content}, f"真实调用 {provider}/{model}{suffix}，输出到 state.{output_field}"


def _execute_live_agent(node: NodeIR, state: dict[str, Any], model_config: ModelRuntimeConfig, skills: SkillRuntimeConfig) -> tuple[dict[str, Any], str]:
    config = node.config
    provider, model = _resolve_node_model(config, model_config, "openai", "gpt-4.1-mini")
    system_prompt = render_template(str(config.get("systemPrompt", "")), state).strip()
    system_prompt = _append_selected_skills(system_prompt, _selected_skill_configs(config, skills))
    user_prompt = str(config.get("userPrompt", "")).strip()
    if user_prompt:
        user_text = render_template(user_prompt, state)
    else:
        user_text = _agent_state_prompt(state)
    messages: list[tuple[str, str]] = []
    if system_prompt:
        messages.append(("system", system_prompt))
    messages.append(("user", user_text))
    response = _call_chat_model(provider, model, messages, model_config)
    content = getattr(response, "content", str(response))
    output_field = str(config.get("outputField", f"{node.id}_result"))
    tools = str(config.get("tools", "")).strip()
    tool_hint = f"，参考工具/前置结果：{tools}" if tools else ""
    skill_count = len(_selected_skill_configs(config, skills))
    skill_hint = f"，注入 {skill_count} 个 Skill" if skill_count else ""
    return {output_field: content}, f"真实调用 Agent 模型 {provider}/{model}{tool_hint}{skill_hint}，输出到 state.{output_field}"


def _execute_skill_node(node: NodeIR, skills: SkillRuntimeConfig, dry_run: bool) -> tuple[dict[str, Any], str]:
    config = node.config
    output_field = str(config.get("outputField", "skill_result"))
    skill_id = str(config.get("skillId") or config.get("toolId") or "").strip()
    skill = skills.get(skill_id) if skill_id else None
    skill_name = str((skill or {}).get("name") or config.get("skillName") or config.get("toolName") or node.label)
    content = str((skill or {}).get("content") or config.get("skillContent") or config.get("content") or "")
    if dry_run and not content:
        content = f"[dry-run] {skill_name}"
    mode_text = "模拟读取" if dry_run else "读取"
    return {output_field: content}, f"{mode_text} Skill「{skill_name}」内容到 state.{output_field}"


def _enabled_skills_by_id(project: ProjectIR) -> SkillRuntimeConfig:
    result: SkillRuntimeConfig = {}
    for skill in getattr(project, "skills", []) or []:
        if getattr(skill, "enabled", True) is False:
            continue
        skill_id = str(getattr(skill, "id", "")).strip()
        if not skill_id:
            continue
        result[skill_id] = {
            "id": skill_id,
            "name": str(getattr(skill, "name", "") or skill_id),
            "description": str(getattr(skill, "description", "") or ""),
            "sourcePath": str(getattr(skill, "source_path", "") or ""),
            "filePath": str(getattr(skill, "file_path", "") or ""),
            "content": str(getattr(skill, "content", "") or ""),
        }
    return result


def _selected_skill_configs(config: dict[str, Any], skills: SkillRuntimeConfig) -> list[dict[str, Any]]:
    ids = _json_string_list(config.get("skillIdsJson"))
    fallback_id = str(config.get("skillId") or "").strip()
    if fallback_id and fallback_id not in ids:
        ids.append(fallback_id)
    return [skills[skill_id] for skill_id in ids if skill_id in skills]


def _append_selected_skills(system_prompt: str, selected_skills: list[dict[str, Any]]) -> str:
    if not selected_skills:
        return system_prompt
    sections = ["可用 Skills:"]
    for skill in selected_skills:
        name = str(skill.get("name") or skill.get("id") or "Skill").strip()
        content = str(skill.get("content") or "").strip()
        if content:
            sections.append(f"### {name}\n{content}")
        else:
            sections.append(f"### {name}\n（该 Skill 暂无内容）")
    skill_prompt = "\n\n".join(sections)
    return f"{system_prompt}\n\n{skill_prompt}".strip() if system_prompt else skill_prompt


def _json_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return [item.strip() for item in text.split(",") if item.strip()]
    if not isinstance(parsed, list):
        return []
    return [str(item).strip() for item in parsed if str(item).strip()]


def _execute_live_ai_router(node: NodeIR, state: dict[str, Any], model_config: ModelRuntimeConfig) -> tuple[dict[str, Any], str]:
    config = node.config
    field = str(config.get("routeField", "route_key"))
    fallback = str(config.get("fallback", "other"))
    reason_field = str(config.get("reasonField", "route_reason"))
    keyword_route = _infer_router_key(config, state) or fallback
    if str(config.get("routeMode", "keyword")) != "llm":
        return {field: keyword_route, reason_field: "live-run keyword router"}, f"关键词路由选择 {keyword_route}"

    provider, model = _resolve_node_model(config, model_config, "openai", "gpt-4.1-mini")
    text = render_template(str(config.get("inputText", "{{ state.messages }}")), state)
    prompt = _router_prompt(str(config.get("instruction", "")), text, _parse_router_scenarios(str(config.get("scenarios", ""))), fallback)
    try:
        response = _call_chat_model(provider, model, [("user", prompt)], model_config)
    except Exception as exc:
        return {field: keyword_route, reason_field: f"llm router failed, fallback to keyword: {exc}"}, f"LLM 路由失败，回退到 {keyword_route}"
    route = _normalize_route_key(getattr(response, "content", str(response)), config, fallback)
    return {field: route, reason_field: "live-run llm router"}, f"LLM 路由选择 {route}"


def _execute_live_human_approval(node: NodeIR, state: dict[str, Any]) -> tuple[dict[str, Any], str]:
    config = node.config
    action_field = str(config.get("actionField", "approval_action"))
    output_field = str(config.get("outputField", "approval_result"))
    action = str(state.get(action_field) or config.get("previewAction") or config.get("defaultAction", "approved"))
    prompt = render_template(str(config.get("prompt", "")), state)
    result = {
        "action": action,
        "prompt": prompt,
        "status": "live-preview",
    }
    return {action_field: action, output_field: result}, f"使用预览审批动作 {action}，继续流程"


def _execute_live_http(node: NodeIR, state: dict[str, Any]) -> tuple[dict[str, Any], str]:
    config = node.config
    output_field = str(config.get("outputField", f"{node.id}_response"))
    if _truthy(config.get("mockEnabled")) or str(config.get("mockResponseJson", "")).strip():
        value = _render_mock_response(str(config.get("mockResponseJson", "")), state)
        return {output_field: value}, f"使用 HTTP mock 响应写入 state.{output_field}"

    method = str(config.get("method", "GET")).upper()
    url = render_template(str(config.get("url", "")), state).strip()
    if not url:
        raise RuntimeError("HTTP 节点缺少 URL。")
    headers: dict[str, str] = {}
    auth_secret = str(config.get("authSecret", "")).strip()
    if auth_secret:
        token = os.getenv(auth_secret, "").strip()
        if not token:
            raise RuntimeError(f"HTTP 节点引用的环境变量 {auth_secret} 未设置。")
        headers["Authorization"] = f"Bearer {token}"
    body = str(config.get("body", ""))
    response = httpx.request(
        method,
        url,
        headers=headers,
        content=render_template(body, state) if body else None,
        timeout=_positive_float(config.get("timeoutSeconds", 30), 30),
    )
    response.raise_for_status()
    try:
        value = response.json()
    except ValueError:
        value = response.text
    return {output_field: value}, f"真实 HTTP {method} {url}，写入 state.{output_field}"


def _execute_live_tool(
    node: NodeIR,
    state: dict[str, Any],
    model_config: ModelRuntimeConfig,
    tools: ToolRuntimeConfig,
) -> tuple[dict[str, Any], str]:
    config = node.config
    source = str(config.get("source", "")).strip().lower()
    legacy_single_tool = not _json_string_list(config.get("toolIdsJson")) and not _json_object_list(config.get("toolRegistryJson"))
    if legacy_single_tool and (source == "http" or str(config.get("url", "")).strip() or str(config.get("mockResponseJson", "")).strip()):
        return _execute_live_http(node, state)
    output_field = str(config.get("outputField", f"{node.id}_result"))
    selected_tools = _selected_tool_configs(config, tools)
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

    provider, model = _resolve_node_model(config, model_config, "openai", "gpt-4.1-mini")
    max_iterations = min(_positive_int(config.get("maxIterations", 4), 4), 12)
    system_prompt = render_template(str(config.get("systemPrompt", "")), state).strip()
    messages: list[tuple[str, str]] = [
        ("system", _tools_agent_system_prompt(system_prompt, selected_tools, max_iterations)),
        ("user", render_template(str(config.get("userPrompt") or _agent_state_prompt(state)), state)),
    ]
    calls: list[dict[str, Any]] = []
    final_answer = ""
    for iteration in range(max_iterations):
        response = _call_chat_model(provider, model, messages, model_config)
        content = getattr(response, "content", str(response))
        decision = _parse_tool_agent_decision(content)
        tool_calls = _normalize_tool_calls(decision.get("tool_calls"))
        if not tool_calls:
            final_answer = _first_config_value(decision.get("final_answer"), content)
            break

        observations: list[dict[str, Any]] = []
        for call_index, tool_call in enumerate(tool_calls, start=1):
            tool_name = str(tool_call.get("tool") or tool_call.get("name") or "").strip()
            args = tool_call.get("args") if isinstance(tool_call.get("args"), dict) else {}
            tool_config = _find_selected_tool(selected_tools, tool_name)
            if not tool_config:
                observation = {"ok": False, "error": f"未知 Tool：{tool_name}"}
            else:
                observation = _invoke_registered_tool(tool_config, args)
            calls.append(
                {
                    "iteration": iteration + 1,
                    "index": call_index,
                    "tool": tool_name,
                    "args": args,
                    "observation": observation,
                }
            )
            observations.append({"tool": tool_name, "observation": observation})
        messages.append(("assistant", content))
        messages.append(("user", "工具执行结果：\n" + json.dumps(observations, ensure_ascii=False, indent=2) + "\n请继续；如果已经足够，请返回 final_answer。"))
    else:
        final_answer = f"达到最大工具调用轮次 {max_iterations}，已停止。"

    return {
        output_field: final_answer,
        f"{output_field}_tool_calls": calls,
    }, f"Tools Agent 注册 {len(selected_tools)} 个 Tool，执行 {len(calls)} 次工具调用，输出到 state.{output_field}"


def _tools_agent_system_prompt(system_prompt: str, selected_tools: list[dict[str, Any]], max_iterations: int) -> str:
    tool_lines = []
    for tool in selected_tools:
        schema = _parse_json_object(str(tool.get("schemaJson", "{}")))
        properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        required = schema.get("required") if isinstance(schema.get("required"), list) else []
        tool_lines.append(
            {
                "id": tool.get("id"),
                "name": tool.get("name"),
                "source": tool.get("source"),
                "description": tool.get("description"),
                "args": properties,
                "required": required,
            }
        )
    instructions = (
        "你是一个可以自主调用工具的 Agent。"
        f"最多进行 {max_iterations} 轮工具调用；同一个工具可以反复调用，也可以在同一轮调用多个不同工具。"
        "每次回复必须是 JSON，格式为："
        '{"tool_calls":[{"tool":"工具名称","args":{}}],"final_answer":""}。'
        "如果还需要工具，填写 tool_calls；如果已经完成，tool_calls 为空数组，并填写 final_answer。"
        "不要输出 Markdown。"
    )
    registry = "可用工具：\n" + json.dumps(tool_lines, ensure_ascii=False, indent=2)
    return "\n\n".join(part for part in (system_prompt, instructions, registry) if part).strip()


def _parse_tool_agent_decision(content: str) -> dict[str, Any]:
    text = str(content or "").strip()
    if not text:
        return {"tool_calls": [], "final_answer": ""}
    candidates = [text]
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        candidates.insert(0, fenced.group(1).strip())
    start = text.find("{")
    end = text.rfind("}")
    if 0 <= start < end:
        candidates.append(text[start : end + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, list):
            return {"tool_calls": parsed, "final_answer": ""}
        if isinstance(parsed, dict):
            return parsed
    return {"tool_calls": [], "final_answer": text}


def _normalize_tool_calls(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    calls: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            calls.append(item)
    return calls


def _invoke_registered_tool(tool_config: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    schema = _parse_json_object(str(tool_config.get("schemaJson", "{}")))
    metadata = schema.get("x-graphic") if isinstance(schema.get("x-graphic"), dict) else {}
    kind = str(metadata.get("kind") or "").strip()
    source = str(tool_config.get("source") or "").strip().lower()
    try:
        if source == "python" or kind == "python_function":
            result = _invoke_python_tool(metadata, args)
            return {"ok": True, "result": _compact_tool_result(result)}
        if source in {"openapi", "http"} or kind == "openapi_operation":
            return {
                "ok": True,
                "status": "registered_not_executed",
                "message": "该工具已注册为 OpenAPI/HTTP 工具，预览运行暂未配置真实 baseUrl 调用。",
                "operation": {
                    "method": metadata.get("method"),
                    "path": metadata.get("path"),
                },
                "args": args,
            }
        return {
            "ok": True,
            "status": "registered",
            "tool": tool_config.get("name"),
            "source": source or "json",
            "args": args,
        }
    except Exception as exc:
        return {"ok": False, "error": f"{exc.__class__.__name__}: {exc}"}


def _invoke_python_tool(metadata: dict[str, Any], args: dict[str, Any]) -> Any:
    source_path = str(metadata.get("sourcePath") or "").strip()
    function_name = str(metadata.get("function") or "").strip()
    if not source_path or not function_name:
        raise RuntimeError("Python Tool 缺少 sourcePath 或 function 元数据。")
    path = Path(source_path).expanduser()
    if not path.is_absolute():
        path = ROOT_DIR / path
    if not path.is_file():
        raise RuntimeError(f"Python Tool 文件不存在：{path}")
    module_name = f"graphic_tool_{abs(hash(path))}_{path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 Python Tool 文件：{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    function = getattr(module, function_name, None)
    if function is None:
        raise RuntimeError(f"Python Tool 函数不存在：{function_name}")
    if hasattr(function, "invoke") and callable(function.invoke):
        result = function.invoke(args)
    elif callable(function):
        result = function(**args)
    else:
        raise RuntimeError(f"Python Tool 不可调用：{function_name}")
    if inspect.isawaitable(result):
        result = _run_awaitable(result)
    return result


def _run_awaitable(value: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(value)
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(value)
    finally:
        loop.close()


def _compact_tool_result(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value if not isinstance(value, str) or len(value) <= 4000 else value[:4000] + "...[truncated]"
    try:
        json.dumps(value, ensure_ascii=False)
        return _compact_value(value)
    except TypeError:
        return str(value)


def _find_selected_tool(selected_tools: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    normalized = name.strip().lower()
    if not normalized:
        return None
    for tool in selected_tools:
        candidates = {str(tool.get("id") or "").lower(), str(tool.get("name") or "").lower()}
        if normalized in candidates:
            return tool
    return None


def _selected_tool_configs(config: dict[str, Any], tools: ToolRuntimeConfig) -> list[dict[str, Any]]:
    selected_ids = _json_string_list(config.get("toolIdsJson"))
    snapshot_tools = _json_object_list(config.get("toolRegistryJson"))
    snapshot_by_id = {str(tool.get("id") or "").strip(): tool for tool in snapshot_tools if str(tool.get("id") or "").strip()}
    if not selected_ids and snapshot_tools:
        selected_ids = [str(tool.get("id") or "").strip() for tool in snapshot_tools if str(tool.get("id") or "").strip()]
    legacy_name = str(config.get("toolName") or "").strip()
    if legacy_name and legacy_name not in selected_ids:
        selected_ids.append(legacy_name)
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for tool_id in selected_ids:
        tool = tools.get(tool_id) or snapshot_by_id.get(tool_id)
        if not tool:
            tool = next((item for item in tools.values() if str(item.get("name") or "") == tool_id), None)
        if not tool:
            continue
        key = str(tool.get("id") or tool.get("name") or tool_id)
        if key in seen:
            continue
        seen.add(key)
        result.append(tool)
    return result


def _json_object_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    text = str(value or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return []
    return [item for item in parsed if isinstance(item, dict)] if isinstance(parsed, list) else []


def _tool_configs_by_id(project: ProjectIR) -> ToolRuntimeConfig:
    result: ToolRuntimeConfig = {}
    for tool in _workspace_tool_dicts():
        _register_tool_config(result, tool)
    for tool in getattr(project, "tools", []) or []:
        _register_tool_config(result, _model_to_tool_dict(tool))
    for node in project.nodes:
        for tool in _json_object_list(node.config.get("toolRegistryJson")):
            _register_tool_config(result, tool)
    return result


def _workspace_tool_dicts() -> list[dict[str, Any]]:
    if not WORKSPACE_TOOLS_FILE.exists():
        return []
    try:
        data = json.loads(WORKSPACE_TOOLS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


def _model_to_tool_dict(tool: Any) -> dict[str, Any]:
    if isinstance(tool, dict):
        return tool
    if hasattr(tool, "model_dump"):
        return tool.model_dump(by_alias=True)
    return {
        "id": str(getattr(tool, "id", "") or ""),
        "name": str(getattr(tool, "name", "") or ""),
        "description": str(getattr(tool, "description", "") or ""),
        "source": str(getattr(tool, "source", "") or ""),
        "schemaJson": str(getattr(tool, "tool_schema", "") or "{}"),
    }


def _register_tool_config(registry: ToolRuntimeConfig, tool: dict[str, Any]) -> None:
    tool_id = str(tool.get("id") or "").strip()
    name = str(tool.get("name") or "").strip()
    if not tool_id and not name:
        return
    normalized = {
        "id": tool_id or name,
        "name": name or tool_id,
        "description": str(tool.get("description") or ""),
        "source": str(tool.get("source") or "python"),
        "schemaJson": str(tool.get("schemaJson") or tool.get("tool_schema") or "{}"),
    }
    registry[normalized["id"]] = normalized
    registry[normalized["name"]] = normalized


def _execute_live_retriever(node: NodeIR, state: dict[str, Any]) -> tuple[dict[str, Any], str]:
    config = node.config
    output_field = str(config.get("outputField", f"{node.id}_context"))
    root = _resolve_path(str(config.get("path", "./knowledge")))
    top_k = _positive_int(config.get("topK", 4), 4)
    query = render_template(str(config.get("query", "{{ state.messages }}")), state)
    if not root.exists():
        return {output_field: ""}, f"知识库目录不存在：{root}"

    if _is_chroma_retriever(config, root):
        return _execute_live_chroma_retriever(config, root, output_field, query, top_k)

    files = sorted(path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES)
    ranked = _rank_documents(files, query)
    selected = ranked[:top_k] if ranked else []
    context_parts = []
    for score, path, text in selected:
        try:
            source = path.relative_to(root).as_posix()
        except ValueError:
            source = path.as_posix()
        context_parts.append(f"来源: {source}\n相关度: {score}\n{text[:2400]}")
    return {
        output_field: "\n\n---\n\n".join(context_parts),
    }, f"检索 {len(files)} 个文档，返回 {len(context_parts)} 段到 state.{output_field}"


def _is_chroma_retriever(config: dict[str, Any], root: Path) -> bool:
    source = str(config.get("source", "")).strip().lower()
    source_type = str(config.get("sourceType", "")).strip().lower()
    return source == "vectorstore" or source_type == "vectorstore" or (root / "chroma.sqlite3").exists()


def _execute_live_chroma_retriever(
    config: dict[str, Any],
    root: Path,
    output_field: str,
    query: str,
    top_k: int,
) -> tuple[dict[str, Any], str]:
    try:
        import chromadb
    except ImportError as exc:
        raise RuntimeError("后端缺少 chromadb，请安装 requirements-dev.txt 后重试。") from exc

    hints = _chroma_runtime_hints(config, root)
    try:
        client = chromadb.PersistentClient(path=str(root))
        collection_name = _first_config_value(
            config.get("collection"),
            hints.get("collection"),
            hints.get("collectionName"),
            hints.get("COLLECTION_NAME"),
        )
        collection = _get_chroma_collection(client, collection_name)
        collection_name = getattr(collection, "name", collection_name or "default")
        count = int(collection.count())
        if count <= 0:
            return {output_field: ""}, f"Chroma collection {collection_name} 为空。"

        include = ["documents", "metadatas", "distances"]
        n_results = min(top_k, count)
        query_embedding = _build_chroma_query_embedding(config, hints, query)
        if query_embedding:
            result = collection.query(query_embeddings=[query_embedding], n_results=n_results, include=include)
            detail_mode = "query_embeddings"
        else:
            result = collection.query(query_texts=[query], n_results=n_results, include=include)
            detail_mode = "query_texts"
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(_format_chroma_error(exc, bool(_chroma_embedding_model(config, hints)))) from exc

    context_parts = _format_chroma_results(result)
    return {
        output_field: "\n\n---\n\n".join(context_parts),
    }, f"查询 Chroma collection {collection_name}（{count} 条，{detail_mode}），返回 {len(context_parts)} 段到 state.{output_field}"


def _get_chroma_collection(client: Any, collection_name: str) -> Any:
    if collection_name:
        return client.get_collection(name=collection_name)
    collections = client.list_collections()
    if not collections:
        raise RuntimeError("Chroma 目录中没有可用 collection。")
    first = collections[0]
    first_name = getattr(first, "name", str(first))
    return client.get_collection(name=first_name)


def _chroma_runtime_hints(config: dict[str, Any], root: Path) -> dict[str, Any]:
    hints = _parse_json_object(str(config.get("metadataJson", "") or "{}"))
    sidecar = _read_chroma_sidecar_config(root)
    for key, value in sidecar.items():
        hints.setdefault(key, value)
    return hints


def _read_chroma_sidecar_config(root: Path) -> dict[str, Any]:
    candidates = [root / "runtime_config.json", root.parent / "runtime_config.json"]
    for path in candidates:
        if not path.exists() or not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            return data
    return {}


def _build_chroma_query_embedding(config: dict[str, Any], hints: dict[str, Any], query: str) -> list[float] | None:
    model = _chroma_embedding_model(config, hints)
    base_url = _first_config_value(
        hints.get("embeddingBaseUrl"),
        hints.get("embeddingApiBase"),
        hints.get("baseUrl"),
        hints.get("apiBase"),
        hints.get("EMBEDDING_API_BASE"),
    )
    api_key_env = _first_config_value(hints.get("embeddingApiKeyEnv"), hints.get("apiKeyEnv"), hints.get("EMBEDDING_API_KEY_ENV"))
    api_key = _first_config_value(hints.get("embeddingApiKey"), hints.get("apiKey"), hints.get("EMBEDDING_API_KEY"), _read_api_key(api_key_env))
    if not model or not base_url:
        return None
    if not api_key:
        raise RuntimeError("Chroma 查询需要生成 query embedding，但没有可用的 embedding API Key。请在 RAG 元数据 JSON 配置 embeddingApiKeyEnv，或设置 EMBEDDING_API_KEY。")
    return _call_openai_compatible_embedding(model, base_url, api_key, query)


def _chroma_embedding_model(config: dict[str, Any], hints: dict[str, Any]) -> str:
    metadata_model = _first_config_value(hints.get("embeddingModel"))
    if metadata_model:
        return metadata_model
    config_model = _first_config_value(config.get("embeddingModel"))
    sidecar_model = _first_config_value(hints.get("EMBEDDING_MODEL"))
    if config_model and config_model != "bge-m3":
        return config_model
    return sidecar_model or config_model


def _call_openai_compatible_embedding(model: str, base_url: str, api_key: str, query: str) -> list[float]:
    url = base_url.rstrip("/")
    if not url.endswith("/embeddings"):
        url = f"{url}/embeddings"
    payload = json.dumps({"model": model, "input": query}, ensure_ascii=False).encode("utf-8")
    request = urllib_request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib_request.urlopen(request, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))
    except URLError as exc:
        raise RuntimeError(f"Embedding 接口调用失败：{exc}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("Embedding 接口返回了无法解析的 JSON。") from exc

    try:
        embedding = body["data"][0]["embedding"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("Embedding 接口响应缺少 data[0].embedding。") from exc
    if not isinstance(embedding, list) or not embedding:
        raise RuntimeError("Embedding 接口返回的 embedding 为空。")
    return [float(value) for value in embedding]


def _format_chroma_results(result: dict[str, Any]) -> list[str]:
    ids = _first_result_list(result.get("ids"))
    documents = _first_result_list(result.get("documents"))
    metadatas = _first_result_list(result.get("metadatas"))
    distances = _first_result_list(result.get("distances"))
    context_parts: list[str] = []
    for index, document in enumerate(documents):
        text = "" if document is None else str(document)
        metadata = metadatas[index] if index < len(metadatas) and isinstance(metadatas[index], dict) else {}
        source = _metadata_source(metadata) or (str(ids[index]) if index < len(ids) else f"document_{index + 1}")
        distance = distances[index] if index < len(distances) else None
        lines = [f"来源: {source}"]
        if distance is not None:
            lines.append(f"距离: {distance}")
        if metadata:
            lines.append(f"元数据: {json.dumps(metadata, ensure_ascii=False)}")
        lines.append(text[:2400])
        context_parts.append("\n".join(lines))
    return context_parts


def _metadata_source(metadata: dict[str, Any]) -> str:
    for key in ("source", "file", "filename", "path", "url", "title"):
        value = metadata.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _first_result_list(value: Any) -> list[Any]:
    if not isinstance(value, list) or not value:
        return []
    first = value[0]
    return first if isinstance(first, list) else value


def _parse_json_object(value: str) -> dict[str, Any]:
    if not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _first_config_value(*values: Any) -> str:
    for value in values:
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _format_chroma_error(exc: Exception, has_embedding_model: bool) -> str:
    message = str(exc)
    if "dimension" in message.lower() or "embedding" in message.lower():
        if has_embedding_model:
            return f"Chroma 查询失败：{message}"
        return (
            "Chroma 查询失败：该 collection 可能使用了非默认 embedding 维度。"
            "请在 RAG 配置中填写 Embedding 模型，并在元数据 JSON 配置 embeddingBaseUrl 与 embeddingApiKeyEnv。"
            f"原始错误：{message}"
        )
    return f"Chroma 查询失败：{message}"


def _call_chat_model(
    provider: str,
    model: str,
    messages: list[tuple[str, str]],
    runtime_config: ModelRuntimeConfig = None,
) -> Any:
    provider_key = _normalize_provider(provider)
    base_url = _runtime_value(runtime_config, "baseUrl", "base_url")
    api_key_env = _safe_api_key_env(_runtime_value(runtime_config, "apiKeyEnv", "api_key_env"))
    api_key = _runtime_value(runtime_config, "apiKey", "api_key") or _read_api_key(api_key_env)
    organization = _runtime_value(runtime_config, "organization")
    api_version = _runtime_value(runtime_config, "apiVersion", "api_version")

    try:
        if provider_key == "azure_openai":
            return _call_azure_openai(model, messages, base_url, api_key, api_key_env, api_version)
        if provider_key in OPENAI_COMPATIBLE_PROVIDERS or base_url:
            return _call_openai_compatible(provider_key, model, messages, base_url, api_key, api_key_env, organization)

        from langchain.chat_models import init_chat_model
    except ImportError as exc:
        raise RuntimeError("后端缺少 LangChain 模型运行依赖，请安装 requirements-dev.txt 后重试。") from exc

    try:
        kwargs: dict[str, Any] = {}
        if api_key:
            kwargs["api_key"] = api_key
        chat_model = init_chat_model(model, model_provider=PROVIDER_ALIASES.get(provider_key, provider_key), **kwargs)
        return chat_model.invoke(messages)
    except Exception as exc:
        raise RuntimeError(f"模型调用失败：{exc}") from exc


def _call_openai_compatible(
    provider: str,
    model: str,
    messages: list[tuple[str, str]],
    base_url: str,
    api_key: str,
    api_key_env: str,
    organization: str,
) -> Any:
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:
        raise RuntimeError("后端缺少 langchain-openai，请安装 requirements-dev.txt 后重试。") from exc

    resolved_base_url = base_url or OPENAI_COMPATIBLE_BASE_URLS.get(provider, "")
    resolved_api_key = api_key or ("ollama" if provider == "ollama" else "")
    if not resolved_api_key and resolved_base_url and not api_key_env:
        resolved_api_key = "not-needed"
    if not resolved_api_key and api_key_env:
        raise RuntimeError(f"模型配置引用的环境变量 {api_key_env} 未设置。")

    kwargs: dict[str, Any] = {"model": model}
    if resolved_base_url:
        kwargs["base_url"] = resolved_base_url
    if resolved_api_key:
        kwargs["api_key"] = resolved_api_key
    if organization:
        kwargs["organization"] = organization
    chat_model = ChatOpenAI(**kwargs)
    return chat_model.invoke(messages)


def _call_azure_openai(
    model: str,
    messages: list[tuple[str, str]],
    azure_endpoint: str,
    api_key: str,
    api_key_env: str,
    api_version: str,
) -> Any:
    try:
        from langchain_openai import AzureChatOpenAI
    except ImportError as exc:
        raise RuntimeError("后端缺少 langchain-openai，请安装 requirements-dev.txt 后重试。") from exc

    if not azure_endpoint:
        raise RuntimeError("Azure OpenAI 运行配置需要填写 Base URL/Azure Endpoint。")
    if not api_version:
        raise RuntimeError("Azure OpenAI 运行配置需要填写 API Version。")
    if not api_key and api_key_env:
        raise RuntimeError(f"模型配置引用的环境变量 {api_key_env} 未设置。")

    kwargs: dict[str, Any] = {
        "azure_deployment": model,
        "azure_endpoint": azure_endpoint,
        "api_version": api_version,
    }
    if api_key:
        kwargs["api_key"] = api_key
    chat_model = AzureChatOpenAI(**kwargs)
    return chat_model.invoke(messages)


def _normalize_model_config(config: ModelRuntimeConfig) -> ModelRuntimeConfig:
    if not config:
        return None
    if config.get("enabled") is False:
        return None
    return {str(key): value for key, value in config.items() if value is not None}


def _runtime_value(config: ModelRuntimeConfig, *keys: str) -> str:
    if not config:
        return ""
    for key in keys:
        value = config.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _resolve_node_model(
    config: dict[str, Any],
    runtime_config: ModelRuntimeConfig,
    default_provider: str,
    default_model: str,
) -> tuple[str, str]:
    node_provider = str(config.get("provider", "")).strip()
    node_model = str(config.get("model", "")).strip()
    runtime_provider = _runtime_value(runtime_config, "provider")
    runtime_model = _runtime_value(runtime_config, "model")
    has_explicit_node_model = bool(config.get("modelConfigId") or config.get("modelConfigName")) or (
        bool(node_model) and node_model != default_model
    )
    if has_explicit_node_model:
        return node_provider or runtime_provider or default_provider, node_model or runtime_model or default_model
    return runtime_provider or node_provider or default_provider, runtime_model or node_model or default_model


def _read_api_key(api_key_env: str) -> str:
    if not api_key_env:
        return ""
    return os.getenv(api_key_env, "").strip()


def _safe_api_key_env(value: str) -> str:
    return value if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value or "") else ""


def _normalize_provider(provider: str) -> str:
    return provider.strip().lower().replace("-", "_") or "openai"


def render_template(template: str, state: dict[str, Any]) -> str:
    def replace(match: re.Match[str]) -> str:
        return _state_value_to_text(state.get(match.group(1), ""))

    return TEMPLATE_RE.sub(replace, template)


def _rank_documents(files: list[Path], query: str) -> list[tuple[int, Path, str]]:
    terms = _query_terms(query)
    ranked: list[tuple[int, Path, str]] = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        lowered = text.lower()
        if not terms:
            score = 1
        else:
            score = sum(lowered.count(term) for term in terms)
        if score > 0:
            ranked.append((score, path, text))
    ranked.sort(key=lambda item: (-item[0], item[1].as_posix()))
    if ranked:
        return ranked

    fallback: list[tuple[int, Path, str]] = []
    for path in files:
        try:
            fallback.append((0, path, path.read_text(encoding="utf-8")))
        except UnicodeDecodeError:
            continue
    return fallback


def _query_terms(query: str) -> list[str]:
    normalized = query.lower()
    terms = [term for term in re.split(r"[\s,，。！？；;:：、/\\]+", normalized) if len(term) >= 2]
    cjk_pairs = re.findall(r"[\u4e00-\u9fff]{2,}", normalized)
    for phrase in cjk_pairs:
        terms.extend(phrase[index : index + 2] for index in range(max(0, len(phrase) - 1)))
    return sorted(set(terms), key=lambda item: (-len(item), item))


def _choose_handle(node: NodeIR, state: dict[str, Any]) -> str:
    config = node.config
    if node.type == NodeType.CONDITION:
        field = str(config.get("field", ""))
        current = state.get(field)
        expected = str(config.get("value", ""))
        matched = _compare(current, expected, str(config.get("operator", "equals")))
        return str(config.get("trueBranch" if matched else "falseBranch", config.get("fallback", "fallback")))
    if node.type == NodeType.AI_ROUTER:
        return str(state.get(str(config.get("routeField", "route_key"))) or config.get("fallback", "other"))
    if node.type == NodeType.HUMAN_APPROVAL:
        return str(state.get(str(config.get("actionField", "approval_action"))) or config.get("fallback", "rejected"))
    return str(config.get("fallback", "fallback"))


def _compare(current: Any, expected: str, operator: str) -> bool:
    current_text = "" if current is None else str(current)
    if operator == "not_equals":
        return current_text != expected
    if operator == "contains":
        return expected in current_text
    if operator == "not_contains":
        return expected not in current_text
    if operator == "is_empty":
        return not current_text
    if operator == "is_not_empty":
        return bool(current_text)
    return current_text == expected


def _infer_router_key(config: dict[str, Any], state: dict[str, Any]) -> str | None:
    text = json.dumps(state, ensure_ascii=False).lower()
    for line in str(config.get("scenarios", "")).splitlines():
        parts = (line.split(":", 2) + ["", ""])[:3]
        key = parts[0].strip()
        keywords = [item.strip().lower() for item in parts[2].split(",") if item.strip()]
        if key and keywords and any(keyword in text for keyword in keywords):
            return key
    return None


def _parse_router_scenarios(value: str) -> list[dict[str, Any]]:
    scenarios: list[dict[str, Any]] = []
    for line in value.splitlines():
        line = line.strip()
        if not line:
            continue
        scenario_id, label, keywords = (line.split(":", 2) + ["", ""])[:3]
        scenario_id = scenario_id.strip()
        if not scenario_id:
            continue
        scenarios.append(
            {
                "id": scenario_id,
                "label": label.strip() or scenario_id,
                "keywords": [item.strip() for item in keywords.split(",") if item.strip()],
            }
        )
    return scenarios


def _router_prompt(instruction: str, text: str, scenarios: list[dict[str, Any]], fallback: str) -> str:
    lines = [instruction.strip() or "请判断输入属于哪个路由场景，只输出 route key。"]
    lines.append("可选场景：")
    for scenario in scenarios:
        lines.append(f"- {scenario['id']}: {scenario.get('label') or scenario['id']}")
    lines.append(f"fallback: {fallback}")
    lines.append("输入：")
    lines.append(text)
    return "\n".join(lines)


def _normalize_route_key(value: str, config: dict[str, Any], fallback: str) -> str:
    allowed = {fallback}
    allowed.update(scenario["id"] for scenario in _parse_router_scenarios(str(config.get("scenarios", ""))))
    text = value.strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            text = str(parsed.get("route") or parsed.get("route_key") or parsed.get("key") or "")
    except json.JSONDecodeError:
        pass
    for key in sorted(allowed, key=len, reverse=True):
        if key and key in text:
            return key
    return fallback


def _agent_state_prompt(state: dict[str, Any]) -> str:
    user_text = _state_value_to_text(state.get("messages", ""))
    compact = json.dumps(_compact_state(state), ensure_ascii=False, indent=2)
    return f"用户输入：\n{user_text}\n\n当前流程 state：\n{compact}"


def _render_mock_response(raw: str, state: dict[str, Any]) -> Any:
    rendered = render_template(raw.strip() or "{}", state)
    try:
        return json.loads(rendered)
    except json.JSONDecodeError:
        return rendered


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _normalize_input(input_state: dict[str, Any]) -> dict[str, Any]:
    state = dict(input_state)
    if "messages" not in state:
        if "message" in state:
            state["messages"] = state["message"]
        elif "input" in state:
            state["messages"] = state["input"]
    return state


def _state_value_to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict) and "content" in item:
                parts.append(str(item["content"]))
            else:
                parts.append(_state_value_to_text(item))
        return "\n".join(part for part in parts if part)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _compact_state(state: dict[str, Any]) -> dict[str, Any]:
    return {key: _compact_value(value) for key, value in state.items()}


def _compact_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _compact_value(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_compact_value(item) for item in value[:12]]
    if isinstance(value, str) and len(value) > 1200:
        return value[:1200] + "...[truncated]"
    return value


def _resolve_path(value: str) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return ROOT_DIR / path


def _positive_int(value: Any, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback


def _positive_float(value: Any, fallback: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback


def _format_error(exc: Exception) -> str:
    if isinstance(exc, LiveRunUnsupportedError):
        return str(exc)
    return f"{exc.__class__.__name__}: {exc}"


def _first_target(edges: list) -> str | None:
    return edges[0].target if edges else None


def _target_for_handle(edges: list, handle: str) -> str | None:
    for edge in edges:
        if edge.sourceHandle == handle:
            return edge.target
    return None
